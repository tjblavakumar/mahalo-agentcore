"""Transient arm64 AL2023 EC2 builder host (Task 7b, design §A/§E/§F), offline-synthable.

``MahaloBuilderStack`` stands up a single short-lived EC2 instance used by the
operator to run the Docker-dependent build/deploy steps (``cdk deploy`` with
``-c buildImage=1`` etc.) that the WorkSpaces VDI cannot run (no nested
virtualization -> no local Docker). The operator reaches it over SSM Session
Manager (NO SSH, hence ZERO security-group ingress). It is built, used for a
single owner-demo deploy, then destroyed.

Offline-safety (design §E.2, mirroring ``gitea_stack.py``): a fixed
``availability_zones`` property plus a CREATED (not looked-up) one-public-subnet
VPC means ``cdk synth`` needs no account/region AZ context lookup and no AWS
credentials. The AMI resolves at DEPLOY time via a CloudFormation SSM-parameter
(``ec2.MachineImage.latest_amazon_linux2023``), so synth stays credential-free
and Docker-free (NO ``DockerImageAsset``/``BundlingOptions`` anywhere).

arm64 is mandatory (design §F): the Strands agent image is built
``--platform=linux/arm64`` (agent/Dockerfile), so the builder that produces it
must itself be arm64 (``AmazonLinuxCpuType.ARM_64`` + a Graviton ``t4g`` default).
"""

from __future__ import annotations

from aws_cdk import (
    CfnOutput,
    CfnParameter,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from constructs import Construct

# Root device for an AL2023 instance (gp3 root volume).
_ROOT_DEVICE = "/dev/xvda"
# Repo cloned onto the builder by UserData.
_REPO_URL = "https://github.com/tjblavakumar/mahalo-agentcore.git"
_REPO_DEST = "/home/ssm-user/mahalo-agentcore"
# Pin the builder's CDK CLI to the version confirmed to match
# aws-cdk-lib>=2.251,<3 (NOT a floating ``aws-cdk@2`` which can outrun the lib).
_CDK_CLI_VERSION = "2.1145.0"


class MahaloBuilderStack(Stack):
    """VPC + arm64 AL2023 EC2 + admin instance role for a transient builder host."""

    # Fixed AZ so the dedicated VPC needs NO account/region AZ context lookup —
    # ``ec2.Vpc`` otherwise queries real AZs, which requires credentials and
    # breaks the offline synth gate (design §E.2: no fromLookup, no AWS calls).
    @property
    def availability_zones(self) -> list[str]:
        return [f"{self.region}a"]

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Parameters (operator-tunable instance size / disk). ---
        builder_instance_type = CfnParameter(
            self,
            "BuilderInstanceType",
            type="String",
            default="t4g.large",
            description=(
                "arm64 (Graviton) instance type for the transient builder. "
                "Must be an arm64 family to build the linux/arm64 agent image."
            ),
        )
        builder_volume_size = CfnParameter(
            self,
            "BuilderVolumeSizeGiB",
            type="Number",
            default=40,
            description="Root gp3 volume size (GiB) for the builder toolchain + images.",
        )

        # --- (1) Dedicated VPC: one public subnet, no NAT. Created, NOT looked up. ---
        vpc = ec2.Vpc(
            self,
            "BuilderVpc",
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

        # --- (2) Security group: ZERO ingress (SSM Session Manager only). ---
        # Do NOT call add_ingress_rule — the operator connects via SSM, so the
        # builder exposes no inbound ports at all. Egress stays open for dnf/npm/
        # pip/git/ECR pulls and the cdk deploy's AWS API calls.
        sg = ec2.SecurityGroup(
            self,
            "BuilderSg",
            vpc=vpc,
            description="Transient builder: NO ingress (SSM Session Manager only).",
            allow_all_outbound=True,
        )

        # --- (3) Instance role (design §A.4). ---
        # AmazonSSMManagedInstanceCore enables Session Manager (the ONLY access
        # path, since there is no SSH ingress). AdministratorAccess is
        # deliberately broad: this is a transient, single-owner-demo builder that
        # runs the full ``cdk deploy`` (creating runtime/gateway/memory/api/
        # frontend resources across many services) and is destroyed after one
        # use, so its privilege is lifetime-scoped rather than action-scoped.
        role = iam.Role(
            self,
            "BuilderRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonSSMManagedInstanceCore"
                ),
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AdministratorAccess"
                ),
            ],
        )

        # --- (4) UserData: install the full build toolchain (design §A.5). ---
        # Run as root. NOT ``set -e`` at top: a single failed optional step must
        # not abort the whole bootstrap, so each critical step is guarded inline.
        user_data = ec2.UserData.for_linux()
        user_data.add_commands(
            "set -uxo pipefail",
            # Docker (the whole reason this host exists) — enable + start now.
            "dnf install -y docker && systemctl enable --now docker",
            # Let the SSM session user drive docker without sudo (guarded).
            "usermod -aG docker ssm-user 2>/dev/null || true",
            # git for cloning the repo + any submodules.
            "dnf install -y git",
            # Node 24 for the Next.js 16 frontend build (NodeSource arm64 repo).
            "curl -fsSL https://rpm.nodesource.com/setup_24.x | bash - "
            "&& dnf install -y nodejs || true",
            # Python 3.13 for the CDK app's .venv (tolerant: fall back / skip).
            "dnf install -y python3.13 python3.13-pip "
            "|| dnf install -y python3.13 || true",
            # Ensure AWS CLI v2 is present (AL2023 ships it; install if missing).
            "command -v aws >/dev/null 2>&1 || dnf install -y awscli || true",
            # Pin the CDK CLI to the version matching aws-cdk-lib>=2.251,<3
            # (NOT floating aws-cdk@2 which can outrun the pinned library).
            f"npm install -g aws-cdk@{_CDK_CLI_VERSION} || true",
            # Seed the repo for the operator; re-pull/overwrite is done in the
            # deploy script (FEAT-002). Guarded so a transient clone failure does
            # not abort the bootstrap.
            f'git clone "{_REPO_URL}" {_REPO_DEST} 2>/dev/null || true',
            f"chown -R ssm-user:ssm-user {_REPO_DEST} 2>/dev/null || true",
            # Marker the operator (and the deploy script) polls to know the
            # toolchain finished installing.
            "echo 'builder toolchain ready' > /var/log/builder-ready",
        )

        # --- (5) EC2 instance: arm64 AL2023, role at construction. ---
        # Passing role= here makes the L2 auto-create the CfnInstanceProfile;
        # ``.role`` is read-only after construction, so it must be set now.
        instance = ec2.Instance(
            self,
            "BuilderInstance",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            instance_type=ec2.InstanceType(builder_instance_type.value_as_string),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(
                cpu_type=ec2.AmazonLinuxCpuType.ARM_64,
            ),
            role=role,
            security_group=sg,
            user_data=user_data,
            block_devices=[
                ec2.BlockDevice(
                    device_name=_ROOT_DEVICE,
                    volume=ec2.BlockDeviceVolume.ebs(
                        builder_volume_size.value_as_number,
                        volume_type=ec2.EbsDeviceVolumeType.GP3,
                        delete_on_termination=True,
                    ),
                ),
            ],
        )
        # Public IP so the builder can reach the internet (egress) directly in
        # the public subnet without a NAT gateway.
        instance.instance.associate_public_ip_address = True
        # Transient by design: teardown removes the instance.
        instance.apply_removal_policy(RemovalPolicy.DESTROY)

        self.instance = instance
        self.vpc = vpc
        self.role = role

        CfnOutput(
            self,
            "BuilderInstanceId",
            value=instance.instance_id,
            description="EC2 instance id -> `aws ssm start-session --target <id>`.",
        )
        CfnOutput(
            self,
            "BuilderPublicDns",
            value=instance.instance_public_dns_name,
            description="Public DNS of the transient builder host.",
        )
