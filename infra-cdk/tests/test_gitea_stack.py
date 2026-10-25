"""CDK synth assertion tests for MahaloGiteaStack (Task 7, design Â§C.2/Â§C.5), offline.

The stack must synthesize fully offline (no Docker, no AWS credentials, no
context lookup): a dedicated VPC that is CREATED (not looked up), an EC2 instance
whose UserData runs the Gitea container by image reference (no DockerImageAsset),
a security group with SSH restricted + 3000 ingress, and a dedicated EBS volume.
"""

import aws_cdk as cdk
from aws_cdk import assertions

from mahalo_infra.gitea_stack import MahaloGiteaStack

_ENV = cdk.Environment(account="123456789012", region="us-east-1")


def _template() -> assertions.Template:
    app = cdk.App()
    stack = MahaloGiteaStack(app, "MahaloGiteaStack", env=_ENV)
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
    # The Gitea image is referenced by tag in UserData; no asset-backed image.
    body = tmpl.to_json()
    text = str(body)
    assert "gitea/gitea:1.27.3" in text
    assert "DockerImage" not in text


def test_security_group_ssh_restricted_and_3000_open():
    tmpl = _template()
    sgs = tmpl.find_resources("AWS::EC2::SecurityGroup")
    (sg,) = sgs.values()
    ingress = sg["Properties"]["SecurityGroupIngress"]
    ports = {(r.get("FromPort"), r.get("ToPort")) for r in ingress}
    assert (22, 22) in ports
    assert (3000, 3000) in ports
    # SSH rule's CIDR is a parameter reference (AdminCidr), never a literal
    # 0.0.0.0/0 default.
    ssh_rules = [r for r in ingress if r.get("FromPort") == 22]
    assert ssh_rules
    for rule in ssh_rules:
        cidr = rule.get("CidrIp")
        assert cidr != "0.0.0.0/0"


def test_dedicated_ebs_volume():
    tmpl = _template()
    instances = tmpl.find_resources("AWS::EC2::Instance")
    (instance,) = instances.values()
    block_devices = instance["Properties"].get("BlockDeviceMappings", [])
    gp3 = [
        bd
        for bd in block_devices
        if bd.get("Ebs", {}).get("VolumeType") == "gp3"
    ]
    assert gp3, "expected a dedicated gp3 EBS data volume"


def test_outputs_public_url_and_token_param():
    tmpl = _template()
    outputs = tmpl.find_outputs("*")
    assert "GiteaPublicUrl" in outputs
    assert "GiteaAdapterTokenParam" in outputs


def test_cloudfront_distribution_present():
    tmpl = _template()
    # A single CloudFront distribution fronts Gitea over HTTPS/443.
    tmpl.resource_count_is("AWS::CloudFront::Distribution", 1)
    # The HTTPS front-door URL is exported for the browser.
    outputs = tmpl.find_outputs("*")
    assert "GiteaCloudFrontUrl" in outputs


def test_retain_gitea_data_parameter():
    tmpl = _template()
    params = tmpl.to_json().get("Parameters", {})
    assert "RetainGiteaData" in params
    assert "AdminCidr" in params
    assert "GiteaIngressCidr" in params
