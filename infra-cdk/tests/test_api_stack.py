"""CDK synth assertion tests for MahaloApiStack (Task 6), offline.

On the offline/default branch the API Lambda synthesizes Docker-free: one
python3.13 Lambda with handler app.main.handler, a Function URL AuthType=NONE
(Task 7c), the InvokeAgentRuntime grant on the Runtime ARN, and MAHALO_RUNTIME_ARN
wired in.
"""

import aws_cdk as cdk
from aws_cdk import assertions

from mahalo_infra.api_stack import MahaloApiStack
from mahalo_infra.dashboard_stack import MahaloDashboardStack
from mahalo_infra.memory_identity_stack import MahaloMemoryIdentityStack
from mahalo_infra.runtime_stack import MahaloRuntimeStack

_ENV = cdk.Environment(account="123456789012", region="us-east-1")


def _api_template():
    app = cdk.App()
    memory = MahaloMemoryIdentityStack(app, "MahaloMemoryIdentityStack", env=_ENV)
    runtime = MahaloRuntimeStack(app, "MahaloRuntimeStack", memory_stack=memory, env=_ENV)
    dashboard = MahaloDashboardStack(app, "MahaloDashboardStack", env=_ENV)
    api = MahaloApiStack(
        app,
        "MahaloApiStack",
        runtime_stack=runtime,
        dashboard_stack=dashboard,
        env=_ENV,
    )
    return assertions.Template.from_stack(api)


def test_single_python313_lambda():
    tmpl = _api_template()
    tmpl.resource_count_is("AWS::Lambda::Function", 1)
    tmpl.has_resource_properties(
        "AWS::Lambda::Function",
        {"Runtime": "python3.13", "Handler": "app.main.handler"},
    )


def test_function_url_auth_none():
    tmpl = _api_template()
    tmpl.resource_count_is("AWS::Lambda::Url", 1)
    tmpl.has_resource_properties("AWS::Lambda::Url", {"AuthType": "NONE"})


def test_function_url_cors_block():
    # Task 7c (Â§B): the Function URL is AuthType=NONE; the browser calls it with
    # no AWS credentials and asserts the persona via X-Mahalo-Persona. CORS allows
    # the wildcard origin (no credentials to gate) + Content-Type + the persona
    # header; the old SigV4 headers are gone.
    tmpl = _api_template()
    urls = tmpl.find_resources("AWS::Lambda::Url")
    (url,) = urls.values()
    props = url["Properties"]
    assert props["AuthType"] == "NONE"
    cors = props["Cors"]
    assert set(cors["AllowMethods"]) == {"POST", "GET", "PUT"}
    for header in ("Content-Type", "X-Mahalo-Persona"):
        assert header in cors["AllowHeaders"]
    # The SigV4 headers are no longer allowed (nothing is signed).
    for header in (
        "Authorization",
        "X-Amz-Date",
        "X-Amz-Security-Token",
        "X-Amz-Content-Sha256",
    ):
        assert header not in cors["AllowHeaders"]
    assert cors["MaxAge"] == 300
    # Demo wildcard origin (Â§B): safe because requests carry no credentials.
    assert cors["AllowOrigins"] == ["*"]


def test_runtime_arn_env_and_output():
    tmpl = _api_template()
    fns = tmpl.find_resources("AWS::Lambda::Function")
    (fn,) = fns.values()
    env = fn["Properties"]["Environment"]["Variables"]
    assert "MAHALO_RUNTIME_ARN" in env
    assert env["MAHALO_IDENTITY_ENABLED"] == "false"
    outputs = tmpl.to_json().get("Outputs", {})
    assert "RuntimeApiUrl" in outputs


def test_lambda_role_can_invoke_runtime():
    tmpl = _api_template()
    policies = tmpl.find_resources("AWS::IAM::Policy")
    actions = set()
    for policy in policies.values():
        for stmt in policy["Properties"]["PolicyDocument"]["Statement"]:
            act = stmt["Action"]
            actions.update(act if isinstance(act, list) else [act])
    assert "bedrock-agentcore:InvokeAgentRuntime" in actions
    # Identity off in the MVP: the per-user action is NOT granted.
    assert "bedrock-agentcore:InvokeAgentRuntimeForUser" not in actions
