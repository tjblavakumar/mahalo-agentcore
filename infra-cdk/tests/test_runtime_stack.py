"""CDK synth assertion tests for MahaloRuntimeStack (Task 6), offline.

With the build flag UNSET (the offline/default branch): synth exit 0 with NO
DockerImageAsset, the Runtime referencing the AgentImageUri parameter, one L2
AWS::BedrockAgentCore::Runtime with no JWT authorizer (AWS_IAM default), an
auto-created exec role carrying the Bedrock/Memory statements + the explicit
ECR-pull statement (from_image_uri grants no IAM), the expected env vars, and one
RuntimeEndpoint from add_endpoint("default"). The deploy/from_asset branch is
marked skip when Docker is unavailable so the offline gate never breaks.
"""

import json
import os
import shutil

import aws_cdk as cdk
import pytest
from aws_cdk import assertions

from mahalo_infra.memory_identity_stack import MahaloMemoryIdentityStack
from mahalo_infra.runtime_stack import MahaloRuntimeStack

_ENV = cdk.Environment(account="123456789012", region="us-east-1")


def _template():
    app = cdk.App()
    memory = MahaloMemoryIdentityStack(app, "MahaloMemoryIdentityStack", env=_ENV)
    stack = MahaloRuntimeStack(
        app, "MahaloRuntimeStack", memory_stack=memory, env=_ENV
    )
    return assertions.Template.from_stack(stack), app


def test_single_runtime_and_endpoint():
    tmpl, _ = _template()
    tmpl.resource_count_is("AWS::BedrockAgentCore::Runtime", 1)
    tmpl.resource_count_is("AWS::BedrockAgentCore::RuntimeEndpoint", 1)


def test_runtime_has_no_jwt_authorizer():
    tmpl, _ = _template()
    runtimes = tmpl.find_resources("AWS::BedrockAgentCore::Runtime")
    (runtime,) = runtimes.values()
    props = runtime["Properties"]
    # AWS_IAM default: no custom JWT authorizer block.
    auth = props.get("AuthorizerConfiguration")
    assert not (isinstance(auth, dict) and "CustomJWTAuthorizer" in auth)


def test_runtime_references_image_parameter_offline_branch():
    tmpl, _ = _template()
    params = tmpl.to_json().get("Parameters", {})
    assert "AgentImageUri" in params
    runtimes = tmpl.find_resources("AWS::BedrockAgentCore::Runtime")
    (runtime,) = runtimes.values()
    # The container URI references the AgentImageUri parameter (Ref), not an asset.
    text = json.dumps(runtime["Properties"])
    assert "AgentImageUri" in text


def test_offline_branch_has_no_docker_image_asset():
    tmpl, app = _template()
    # No ECR DockerImageAsset / image asset should be staged on the offline branch.
    assembly = app.synth()
    stack_art = assembly.get_stack_by_name("MahaloRuntimeStack")
    image_assets = [
        a for a in stack_art.assets if a.get("packaging") == "container-image"
    ]
    assert image_assets == []


def test_runtime_env_vars():
    tmpl, _ = _template()
    runtimes = tmpl.find_resources("AWS::BedrockAgentCore::Runtime")
    (runtime,) = runtimes.values()
    env = runtime["Properties"]["EnvironmentVariables"]
    assert env["MAHALO_MEMORY_ENABLED"] == "true"
    assert env["MAHALO_IDENTITY_ENABLED"] == "false"
    assert env["MAHALO_TOOL_MODE"] == "direct"
    assert env["MAHALO_IDENTITY_JIRA_PROVIDER"] == "mahalo-jira-apikey"
    # AWS_PROFILE must NOT be injected (Finding 1 â€” default credential chain).
    assert "AWS_PROFILE" not in env


def test_exec_role_has_bedrock_memory_and_ecr_statements():
    tmpl, _ = _template()
    policies = tmpl.find_resources("AWS::IAM::Policy")
    actions = set()
    for policy in policies.values():
        for stmt in policy["Properties"]["PolicyDocument"]["Statement"]:
            act = stmt["Action"]
            actions.update(act if isinstance(act, list) else [act])
    assert "bedrock:InvokeModel" in actions
    assert "bedrock-agentcore:CreateEvent" in actions
    assert "bedrock-agentcore:ListEvents" in actions
    # from_image_uri branch: explicit ECR pull present.
    assert "ecr:GetAuthorizationToken" in actions
    assert "ecr:BatchGetImage" in actions


def test_runtime_arn_output():
    tmpl, _ = _template()
    outputs = tmpl.to_json().get("Outputs", {})
    assert "RuntimeArn" in outputs


def test_exec_role_grants_three_review_inference_profiles():
    tmpl, _ = _template()
    # The inference-profile ARNs template the account (self.account -> AWS::AccountId
    # Fn::Join), so they are not plain strings; assert the id fragments appear in
    # the serialized IAM policies, and that the InvokeModel action is granted.
    policies = tmpl.find_resources("AWS::IAM::Policy")
    text = json.dumps(policies)
    for profile_id in (
        "inference-profile/us.amazon.nova-lite-v1:0",
        "inference-profile/us.amazon.nova-micro-v1:0",
        "inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0",
    ):
        assert profile_id in text, f"missing inference-profile grant for {profile_id}"
    for base_id in (
        "foundation-model/amazon.nova-lite-v1:0",
        "foundation-model/amazon.nova-micro-v1:0",
        "foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
    ):
        assert base_id in text, f"missing foundation-model grant for {base_id}"


def test_exec_role_does_not_grant_opus():
    tmpl, _ = _template()
    text = json.dumps(tmpl.to_json()).lower()
    assert "opus" not in text, (
        "Opus must not be granted InvokeModel on the Runtime role"
    )


def test_review_model_arns_template_the_account():
    """The review-model inference-profile ARNs template the account via
    self.account — not a hardcoded literal.

    When the stack is synthesized WITHOUT a concrete env (account is an unresolved
    CDK token), self.account renders as a Ref to the AWS::AccountId pseudo-param
    inside an Fn::Join. If the source had baked in a literal account id, the ARN
    would stay a plain string instead. This is the templating guarantee; the
    env-pinned _template() above legitimately resolves the account to the test
    env's value, so it can't be used for this check.
    """
    app = cdk.App()
    memory = MahaloMemoryIdentityStack(app, "MahaloMemoryIdentityStack")
    stack = MahaloRuntimeStack(app, "MahaloRuntimeStack", memory_stack=memory)
    tmpl = assertions.Template.from_stack(stack)
    profile_arns = []
    for policy in tmpl.find_resources("AWS::IAM::Policy").values():
        for stmt in policy["Properties"]["PolicyDocument"]["Statement"]:
            res = stmt.get("Resource")
            for item in res if isinstance(res, list) else [res]:
                if isinstance(item, dict) and "inference-profile/us." in json.dumps(item):
                    profile_arns.append(item)
    # Sonnet + the three review profiles = four templated inference-profile ARNs.
    assert len(profile_arns) == 4, "expected four templated inference-profile ARNs"
    for arn_node in profile_arns:
        assert "Fn::Join" in arn_node, (
            "inference-profile ARN should be an Fn::Join (templated account)"
        )
        joined = json.dumps(arn_node)
        assert "AWS::AccountId" in joined, "account must stay templated via Ref"


@pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="Docker unavailable; the from_asset deploy branch is operator-only.",
)
def test_asset_branch_takes_from_asset(monkeypatch):
    monkeypatch.setenv("MAHALO_BUILD_IMAGE", "1")
    app = cdk.App()
    memory = MahaloMemoryIdentityStack(app, "MahaloMemoryIdentityStack", env=_ENV)
    stack = MahaloRuntimeStack(
        app, "MahaloRuntimeStack", memory_stack=memory, env=_ENV
    )
    assembly = app.synth()
    stack_art = assembly.get_stack_by_name("MahaloRuntimeStack")
    image_assets = [
        a for a in stack_art.assets if a.get("packaging") == "container-image"
    ]
    assert image_assets, "deploy branch should stage a container image asset"
