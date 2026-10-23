"""CDK synth assertion tests for MahaloFrontendStack (Task 7, design §D.2 / Task 7c §C).

Offline: the distribution has a SINGLE S3 origin (no Function-URL origin) and the
bucket is private. Task 7c removed the SCP-blocked Cognito unauthenticated
identity pool + role, so no Cognito resources are present and the stack no longer
takes an ``api_stack`` parameter. The BucketDeployment is flag-gated, so the
default synth needs no prior ``next build``.
"""

import aws_cdk as cdk
from aws_cdk import assertions

from mahalo_infra.frontend_stack import MahaloFrontendStack

_ENV = cdk.Environment(account="<AWS_ACCOUNT_ID>", region="us-east-1")


def _frontend_template(context: dict | None = None) -> assertions.Template:
    app = cdk.App(context=context or {})
    frontend = MahaloFrontendStack(app, "MahaloFrontendStack", env=_ENV)
    return assertions.Template.from_stack(frontend)


def test_private_bucket():
    tmpl = _frontend_template()
    tmpl.resource_count_is("AWS::S3::Bucket", 1)
    tmpl.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            }
        },
    )


def test_distribution_single_s3_origin_no_function_url_origin():
    tmpl = _frontend_template()
    tmpl.resource_count_is("AWS::CloudFront::Distribution", 1)
    dists = tmpl.find_resources("AWS::CloudFront::Distribution")
    (dist,) = dists.values()
    origins = dist["Properties"]["DistributionConfig"]["Origins"]
    assert len(origins) == 1, "expected exactly one (S3) origin"
    # A single S3 origin: it has an S3OriginConfig or an OAC, and NO custom
    # Function-URL origin (which would carry a CustomOriginConfig to lambda-url).
    text = str(dist["Properties"]["DistributionConfig"])
    assert "lambda-url" not in text


def test_spa_error_responses():
    tmpl = _frontend_template()
    dists = tmpl.find_resources("AWS::CloudFront::Distribution")
    (dist,) = dists.values()
    errors = dist["Properties"]["DistributionConfig"]["CustomErrorResponses"]
    codes = {e["ErrorCode"] for e in errors}
    assert {403, 404} <= codes
    for e in errors:
        assert e["ResponsePagePath"] == "/index.html"
        assert e["ResponseCode"] == 200


def test_no_cognito_identity_pool():
    # Task 7c: the SCP-blocked Cognito identity pool + role attachment are gone.
    tmpl = _frontend_template()
    tmpl.resource_count_is("AWS::Cognito::IdentityPool", 0)
    tmpl.resource_count_is("AWS::Cognito::IdentityPoolRoleAttachment", 0)


def test_outputs_frontend_url_only():
    tmpl = _frontend_template()
    outputs = tmpl.find_outputs("*")
    assert "FrontendUrl" in outputs
    assert "IdentityPoolId" not in outputs


def test_bucket_deployment_flag_gated():
    # Default/offline: no BucketDeployment (its custom resource handler Lambda is
    # absent). With -c buildFrontend=1 it would require frontend/out to exist, so
    # only assert the default branch here (the offline gate).
    tmpl = _frontend_template()
    # BucketDeployment synthesizes an AWS::CloudFormation::CustomResource backed
    # by an aws-cdk BucketDeployment Lambda; absent on the offline branch.
    customs = tmpl.find_resources("Custom::CDKBucketDeployment")
    assert customs == {}
