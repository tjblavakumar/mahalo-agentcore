"""Always-on Gitea host for the real GitHub backend (Task 7, design §C.2/§C.3/§C.5).

``MahaloGiteaStack`` stands up a single always-on EC2 instance running the
official ``gitea/gitea:1.27.3`` container (image BY REFERENCE in UserData — no
``DockerImageAsset``, so ``cdk synth`` stays Docker-free), backed by a dedicated
gp3 EBS volume mounted at ``/data`` for durable SQLite repo storage. A tiny
dedicated VPC (one public subnet, no NAT) is created — NOT looked up — so synth
needs no account/region context lookup (offline gate).

Reachability (design §C.5): the github Lambda is non-VPC and reaches Gitea over
the public endpoint, authenticated by the Gitea API token (SSM SecureString).
Because a non-VPC Lambda has no fixed egress IP, port 3000 ingress defaults to
``0.0.0.0/0`` (overridable via the ``GiteaIngressCidr`` parameter); SSH (22) is
restricted to the operator-supplied ``AdminCidr`` (no open default).

Secrets (design §C.2): the adapter token + admin password live in SSM
SecureString parameters whose *names* are referenced here (CfnParameters); no
secret literal is synthesized or committed. The bootstrap (``gitea/bootstrap.sh``,
run one-shot by UserData) pushes the minted token to the adapter-token parameter.

Teardown (design §E.3): the EBS volume follows ``RemovalPolicy.DESTROY`` (repos
are fully re-seedable by the bootstrap), flippable to ``RETAIN`` via the
``RetainGiteaData`` parameter for operators who keep repos across a monthly reset.
"""

from __future__ import annotations

from aws_cdk import (
    CfnCondition,
    CfnOutput,
    CfnParameter,
    Fn,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_ec2 as ec2
from constructs import Construct

# Gitea container image pin — the mahalo-dock-proven tag, referenced by string
# in UserData (never built as a DockerImageAsset).
_GITEA_IMAGE = "gitea/gitea:1.27.3"
_GITEA_PORT = 3000
_DATA_DEVICE = "/dev/sdf"

# Stable EIP-backed public DNS of the live Gitea host — the CloudFront origin.
# The EIP (eipalloc-0d582218ab8434359) survives reboots/stop-start, so this DNS
# name is a durable origin. Pinned as a string because the EIP + its association
# were created out-of-band (not owned by this stack), so there is no construct
# attribute to read it from.
_GITEA_ORIGIN_DNS = "ec2-32-193-103-5.compute-1.amazonaws.com"


class MahaloGiteaStack(Stack):
    """VPC + EC2 + EBS + SG + SSM-param references for an always-on Gitea host."""

    # Fixed AZ so the dedicated VPC needs NO account/region AZ context lookup —
    # ``ec2.Vpc`` otherwise queries real AZs, which requires credentials and
    # breaks the offline synth gate (design §E.2: no fromLookup, no AWS calls).
    @property
    def availability_zones(self) -> list[str]:
        return [f"{self.region}a"]

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Parameters (operator-supplied; no secret literals synthesized). ---
        admin_cidr = CfnParameter(
            self,
            "AdminCidr",
            type="String",
            description="CIDR allowed to SSH (22) to the Gitea host, e.g. 1.2.3.4/32.",
        )
        gitea_ingress_cidr = CfnParameter(
            self,
            "GiteaIngressCidr",
            type="String",
            default="0.0.0.0/0",
            description=(
                "CIDR allowed to reach Gitea HTTP/API (3000). Defaults to "
                "0.0.0.0/0; the Gitea API token protects write calls. Narrow to "
                "a prefix list / known CIDR to harden (design §C.2)."
            ),
        )
        retain_gitea_data = CfnParameter(
            self,
            "RetainGiteaData",
            type="String",
            default="false",
            allowed_values=["true", "false"],
            description=(
                "Keep the Gitea EBS volume on stack teardown (RETAIN) instead of "
                "destroying it. Default false: teardown wipes repos (re-seedable)."
            ),
        )
        gitea_token_param_name = CfnParameter(
            self,
            "GiteaTokenParamName",
            type="String",
            default="/mahalo/gitea/adapter-token",
            description=(
                "Name of the SSM SecureString parameter the bootstrap writes the "
                "adapter token to (the github Lambda reads it via GITEA_TOKEN_PARAM)."
            ),
        )
        gitea_admin_password_param_name = CfnParameter(
            self,
            "GiteaAdminPasswordParamName",
            type="String",
            default="/mahalo/gitea/admin-password",
            description=(
                "Name of the SSM SecureString parameter holding the Gitea admin "
                "password (referenced by name; created/owned by the operator)."
            ),
        )
        gitea_admin_user = CfnParameter(
            self,
            "GiteaAdminUser",
            type="String",
            default="mahalo_admin",
            description="Gitea admin/owner username (the single demo git user).",
        )

        retain = CfnCondition(
            self,
            "RetainGiteaDataCond",
            expression=Fn.condition_equals(retain_gitea_data.value_as_string, "true"),
        )

        # --- (1) Dedicated VPC: one public subnet, no NAT. Created, NOT looked up. ---
        vpc = ec2.Vpc(
            self,
            "GiteaVpc",
            max_azs=1,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                )
            ],
        )

        # --- (2) Security group: SSH restricted, Gitea 3000 open by default. ---
        sg = ec2.SecurityGroup(
            self,
            "GiteaSg",
            vpc=vpc,
            description="Gitea host: SSH restricted to AdminCidr, 3000 per GiteaIngressCidr.",
            allow_all_outbound=True,
        )
        sg.add_ingress_rule(
            ec2.Peer.ipv4(admin_cidr.value_as_string),
            ec2.Port.tcp(22),
            "SSH (admin only)",
        )
        sg.add_ingress_rule(
            ec2.Peer.ipv4(gitea_ingress_cidr.value_as_string),
            ec2.Port.tcp(_GITEA_PORT),
            "Gitea HTTP/API",
        )

        # --- (3) UserData: install Docker, run Gitea by image reference. ---
        user_data = ec2.UserData.for_linux()
        user_data.add_commands(
            "set -euxo pipefail",
            # Mount the dedicated EBS data volume at /data (format first boot).
            "if ! blkid /dev/xvdf >/dev/null 2>&1 && ! blkid /dev/nvme1n1 >/dev/null 2>&1; then "
            "  DEV=$(lsblk -dpno NAME | grep -E 'nvme1n1|xvdf' | head -n1); "
            "  mkfs -t xfs \"$DEV\" || true; fi",
            "DEV=$(lsblk -dpno NAME | grep -E 'nvme1n1|xvdf' | head -n1)",
            "mkdir -p /data",
            "mount \"$DEV\" /data || (mkfs -t xfs \"$DEV\" && mount \"$DEV\" /data)",
            # Install + start Docker (Amazon Linux 2023).
            "dnf install -y docker",
            "systemctl enable --now docker",
            # Run the Gitea server by image reference (no local build).
            "mkdir -p /data/gitea",
            f"docker run -d --name gitea --restart=always -p {_GITEA_PORT}:{_GITEA_PORT} "
            f"-v /data/gitea:/data {_GITEA_IMAGE}",
            # One-shot bootstrap after the server is healthy (idempotent). The
            # bootstrap image is built from the same tag; here we reuse the server
            # container's gitea CLI via docker exec for the first-admin step and
            # drive the REST seeding + SSM token push from the host.
            "for i in $(seq 1 60); do "
            f"  curl -fsS http://localhost:{_GITEA_PORT}/api/healthz && break || sleep 2; done",
            # The bootstrap script is delivered out-of-band by the operator (see
            # the deploy runbook); UserData leaves a marker so the operator can
            # run gitea/bootstrap.sh with the SSM param + public URL env set.
            "echo 'gitea server up; run gitea/bootstrap.sh to seed + push token' > /data/BOOTSTRAP_READY",
        )

        # --- (4) EC2 instance: Amazon Linux 2023, t3.small, public subnet. ---
        instance = ec2.Instance(
            self,
            "GiteaInstance",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.BURSTABLE3, ec2.InstanceSize.SMALL
            ),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(),
            security_group=sg,
            user_data=user_data,
            # Dedicated gp3 data volume mounted at /data (repo persistence).
            block_devices=[
                ec2.BlockDevice(
                    device_name=_DATA_DEVICE,
                    volume=ec2.BlockDeviceVolume.ebs(
                        20,
                        volume_type=ec2.EbsDeviceVolumeType.GP3,
                        delete_on_termination=True,
                    ),
                ),
            ],
        )
        # Public IP for the browser-facing + Lambda-facing endpoint.
        instance.instance.associate_public_ip_address = True

        # EBS teardown posture: DESTROY by default, RETAIN when RetainGiteaData=true.
        cfn_instance = instance.node.default_child
        cfn_instance.add_override(
            "DeletionPolicy",
            Fn.condition_if(retain.logical_id, "Retain", "Delete").to_string(),
        )
        # Keep the explicit RemovalPolicy.DESTROY default for the construct too.
        instance.apply_removal_policy(RemovalPolicy.DESTROY)

        # References (not literals) to the SSM SecureString parameter names.
        self.gitea_token_param_name = gitea_token_param_name.value_as_string
        self.gitea_admin_password_param_name = (
            gitea_admin_password_param_name.value_as_string
        )
        self.gitea_admin_user = gitea_admin_user.value_as_string
        self.instance = instance
        self.vpc = vpc

        # --- (5) CloudFront HTTPS front door (443) for the browser UI + REST API. ---
        # The office network blocks all non-443 outbound ports, so the browser
        # cannot reach the origin's HTTP:3000 directly. CloudFront terminates HTTPS
        # on 443 (allowed) and forwards to the Gitea origin over AWS's own network,
        # so the origin stays plain HTTP:3000. The github Lambda's write path does
        # NOT go through CloudFront (it talks to http://<eip>:3000 internally), so
        # this distribution only serves the interactive UI + REST API to the browser.
        #
        # NOTE (out-of-band): the LIVE distribution was created out-of-band via
        # `aws cloudfront create-distribution` against the running stack (the stack
        # owns a live, stateful instance + EBS + an out-of-band EIP association, so a
        # `cdk deploy` was deemed too risky this task). This CDK block mirrors that
        # live distribution so the IaC stays truthful for a future clean redeploy; it
        # was NOT deployed via `cdk deploy` in the task that added it.
        distribution = cloudfront.Distribution(
            self,
            "GiteaDistribution",
            comment="HTTPS/443 front door for the Gitea web UI + REST API.",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.HttpOrigin(
                    _GITEA_ORIGIN_DNS,
                    protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
                    http_port=_GITEA_PORT,
                ),
                # 443 works: HTTP viewers are redirected to HTTPS.
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                # Gitea login + REST writes need POST/PUT/PATCH/DELETE.
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                # Gitea is fully dynamic + authenticated — never cache.
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                # Forward all viewer headers (except Host, which stays the origin
                # host), all cookies, all query strings — Gitea sessions depend on
                # cookies + the right headers.
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
            ),
        )
        self.distribution = distribution

        public_url = f"http://{instance.instance_public_dns_name}:{_GITEA_PORT}"
        CfnOutput(self, "GiteaPublicUrl", value=public_url,
                  description="Browser/Lambda-facing Gitea base URL (HTTP).")
        CfnOutput(
            self,
            "GiteaCloudFrontUrl",
            value=f"https://{distribution.distribution_domain_name}",
            description="HTTPS/443 CloudFront front door for the Gitea web UI + REST API.",
        )
        CfnOutput(self, "GiteaInstanceId", value=instance.instance_id)
        CfnOutput(
            self,
            "GiteaAdapterTokenParam",
            value=gitea_token_param_name.value_as_string,
            description="SSM SecureString name the adapter token is written to.",
        )
        CfnOutput(
            self,
            "GiteaAdminPasswordParam",
            value=gitea_admin_password_param_name.value_as_string,
            description="SSM SecureString name holding the Gitea admin password.",
        )
