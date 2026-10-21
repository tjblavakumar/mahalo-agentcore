"""CDK synth assertion tests for MahaloFrontendStack (Task 7, design §D.2/§B.2).

Offline: the distribution has a SINGLE S3 origin (no Function-URL origin), the
bucket is private, and the Cognito unauthenticated identity pool + role (granted
only lambda:InvokeFunctionUrl) are present. The BucketDeployment is flag-gated,
so the default synth needs no prior ``next build``.
"""

import aws_cdk as cdk
from aws_cdk import assertions

from mahalo_infra.api_stack import MahaloApiStack
from mahalo_infra.frontend_stack import MahaloFrontendStack
from mahalo_infra.memory_identity_stack import MahaloMemoryIdentityStack
from mahalo_infra.runtime_stack import MahaloRuntimeStack

_ENV = cdk.Environment(account="<AWS_ACCOUNT_ID>", region="us-east-1")


def _frontend_template(context: dict | None = None) -> assertions.Template:
    app = cdk.App(context=context or {})
    memory = MahaloMemoryIdentityStack(app, "MahaloMemoryIdentityStack", env=_ENV)
    runtime = MahaloRuntimeStack(app, "MahaloRuntimeStack", memory_stack=memory, env=_ENV)
    api = MahaloApiStack(app, "MahaloApiStack", runtime_stack=runtime, env=_ENV)
    frontend = MahaloFrontendStack(app, "MahaloFrontendStack", api_stack=api, env=_ENV)
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


def test_identity_pool_unauthenticated():
    tmpl = _frontend_template()
    tmpl.resource_count_is("AWS::Cognito::IdentityPool", 1)
    tmpl.has_resource_properties(
        "AWS::Cognito::IdentityPool",
        {"AllowUnauthenticatedIdentities": True},
    )
    tmpl.resource_count_is("AWS::Cognito::IdentityPoolRoleAttachment", 1)


def test_unauth_role_only_invoke_function_url():
    tmpl = _frontend_template()
    policies = tmpl.find_resources("AWS::IAM::Policy")
    invoke_actions = []
    for policy in policies.values():
        for stmt in policy["Properties"]["PolicyDocument"]["Statement"]:
            act = stmt["Action"]
            acts = act if isinstance(act, list) else [act]
            if "lambda:InvokeFunctionUrl" in acts:
                invoke_actions.append(acts)
    assert invoke_actions, "expected a lambda:InvokeFunctionUrl grant"
    # The grant is scoped to exactly that single action (least privilege).
    for acts in invoke_actions:
        assert acts == ["lambda:InvokeFunctionUrl"]


def test_outputs_identity_pool_and_frontend_url():
    tmpl = _frontend_template()
    outputs = tmpl.find_outputs("*")
    assert "IdentityPoolId" in outputs
    assert "FrontendUrl" in outputs


def test_bucket_deployment_flag_gated():
    # Default/offline: no BucketDeployment (its custom resource handler Lambda is
    # absent). With -c buildFrontend=1 it would require frontend/out to exist, so
    # only assert the default branch here (the offline gate).
    tmpl = _frontend_template()
    # BucketDeployment synthesizes an AWS::CloudFormation::CustomResource backed
    # by an aws-cdk BucketDeployment Lambda; absent on the offline branch.
    customs = tmpl.find_resources("Custom::CDKBucketDeployment")
    assert customs == {}
