"""CDK synth assertion tests for MahaloBuilderStack (Task 7b, design §A/§E/§F), offline.

The transient builder stack must synthesize fully offline (no Docker, no AWS
credentials, no context lookup): a CREATED (not looked-up) one-public-subnet
VPC, an arm64 AL2023 EC2 instance with a 40 GiB gp3 delete-on-termination root
volume, a security group with ZERO ingress (SSM Session Manager only), and an
instance role carrying AmazonSSMManagedInstanceCore.
"""

import aws_cdk as cdk
from aws_cdk import assertions

from mahalo_infra.builder_stack import MahaloBuilderStack

_ENV = cdk.Environment(account="<AWS_ACCOUNT_ID>", region="us-east-1")


def _template() -> assertions.Template:
    app = cdk.App()
    stack = MahaloBuilderStack(app, "MahaloBuilderStack", env=_ENV)
    return assertions.Template.from_stack(stack)


def test_vpc_created_not_looked_up():
    tmpl = _template()
    # A real VPC resource is synthesized (from_lookup would emit no VPC resource
    # and instead require account context).
    tmpl.resource_count_is("AWS::EC2::VPC", 1)
    # One public subnet, no NAT gateway (cost ~0).
    tmpl.resource_count_is("AWS::EC2::NatGateway", 0)
    tmpl.resource_count_is("AWS::EC2::Subnet", 1)


def test_ec2_instance_present():
    tmpl = _template()
    tmpl.resource_count_is("AWS::EC2::Instance", 1)


def test_no_docker_image_asset():
    tmpl = _template()
    # The builder installs Docker at boot; it must not itself be built from a
    # DockerImageAsset / BundlingOptions (offline, Docker-free synth gate).
    text = str(tmpl.to_json())
    assert "DockerImage" not in text


def test_security_group_has_no_ingress():
    tmpl = _template()
    sgs = tmpl.find_resources("AWS::EC2::SecurityGroup")
    (sg,) = sgs.values()
    # ZERO ingress: the operator connects via SSM Session Manager only.
    ingress = sg["Properties"].get("SecurityGroupIngress", [])
    assert ingress == []


def test_instance_is_arm64_al2023():
    tmpl = _template()
    # The AMI resolves at deploy time via an SSM-parameter CfnParameter whose
    # default path points at the arm64 AL2023 image.
    params = tmpl.to_json().get("Parameters", {})
    ssm_ami_params = [
        p
        for name, p in params.items()
        if p.get("Type", "").startswith("AWS::SSM::Parameter::Value")
    ]
    assert ssm_ami_params, "expected an SSM-parameter-backed AMI parameter"
    joined = " ".join(str(p.get("Default", "")) for p in ssm_ami_params)
    assert "al2023" in joined
    assert "arm64" in joined


def test_root_volume_gp3_40gib_delete_on_termination():
    tmpl = _template()
    instances = tmpl.find_resources("AWS::EC2::Instance")
    (instance,) = instances.values()
    block_devices = instance["Properties"].get("BlockDeviceMappings", [])
    gp3 = [
        bd
        for bd in block_devices
        if bd.get("Ebs", {}).get("VolumeType") == "gp3"
    ]
    assert gp3, "expected a gp3 root volume"
    ebs = gp3[0]["Ebs"]
    assert ebs.get("DeleteOnTermination") is True
    # VolumeSize is driven by the BuilderVolumeSizeGiB parameter (Ref), whose
    # default is 40 GiB.
    assert ebs.get("VolumeSize") == {"Ref": "BuilderVolumeSizeGiB"}
    params = tmpl.to_json().get("Parameters", {})
    assert params["BuilderVolumeSizeGiB"]["Default"] == 40


def test_instance_role_has_ssm_core():
    tmpl = _template()
    roles = tmpl.find_resources("AWS::IAM::Role")
    text = str(roles)
    assert "AmazonSSMManagedInstanceCore" in text
    # The instance assumes an EC2 service-principal role via an instance profile.
    tmpl.resource_count_is("AWS::IAM::InstanceProfile", 1)


def test_outputs_instance_id_and_public_dns():
    tmpl = _template()
    outputs = tmpl.find_outputs("*")
    assert "BuilderInstanceId" in outputs
    assert "BuilderPublicDns" in outputs
