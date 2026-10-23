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
