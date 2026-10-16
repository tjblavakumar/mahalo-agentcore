"""CDK synth assertion tests for MahaloGatewayStack (Task 4), offline.

Synths the gateway stack given the four MockServiceStacks and asserts: exactly
one CfnGateway (MCP, authorizerType default AWS_IAM), four CfnGatewayTargets whose
inline toolSchema tool-name sets match the per-service expected names, a Gateway
IAM role granting lambda:InvokeFunction on the four function ARNs, four Lambda
invoke permissions, and no Fn::ImportValue in the template (ARNs flow by direct
construct reference).
"""

import os
import sys

import aws_cdk as cdk
from aws_cdk import assertions

from mahalo_infra.gateway_stack import MahaloGatewayStack
from mahalo_infra.mock_service_stack import MockServiceStack

# tool_schemas for the expected per-service tool names.
_TOOLS_LAMBDAS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "tools-lambdas",
)
if _TOOLS_LAMBDAS not in sys.path:
    sys.path.insert(0, _TOOLS_LAMBDAS)

from common import tool_schemas  # noqa: E402

_ENV = cdk.Environment(account="<AWS_ACCOUNT_ID>", region="us-east-1")
_SERVICES = ("jira", "confluence", "github", "servicenow")
_TARGET_NAMES = {
    "jira": "mock-jira",
    "confluence": "mock-confluence",
    "github": "mock-github",
    "servicenow": "mock-servicenow",
}


def _build():
    """Synth the whole app; return (gateway_template, {svc: mock_template})."""
    app = cdk.App()
    mock_stacks = {}
    for svc in _SERVICES:
        mock_stacks[svc] = MockServiceStack(
            app, f"MahaloMock{svc.capitalize()}Stack", service=svc, env=_ENV
        )
    gw = MahaloGatewayStack(app, "MahaloGatewayStack", mock_stacks=mock_stacks, env=_ENV)
    gw_tmpl = assertions.Template.from_stack(gw)
    mock_tmpls = {
        svc: assertions.Template.from_stack(stack) for svc, stack in mock_stacks.items()
    }
    return gw_tmpl, mock_tmpls


def _template():
    return _build()[0]


def test_single_gateway_mcp_default_aws_iam():
    tmpl = _template()
    tmpl.resource_count_is("AWS::BedrockAgentCore::Gateway", 1)
    gateways = tmpl.find_resources("AWS::BedrockAgentCore::Gateway")
    (gateway,) = gateways.values()
    props = gateway["Properties"]
    assert props["ProtocolType"] == "MCP"
    # authorizerType is a CfnParameter defaulting to AWS_IAM.
    params = tmpl.to_json().get("Parameters", {})
    assert params["AuthorizerType"]["Default"] == "AWS_IAM"


def test_four_targets_with_expected_tool_names():
    tmpl = _template()
    tmpl.resource_count_is("AWS::BedrockAgentCore::GatewayTarget", 4)
    targets = tmpl.find_resources("AWS::BedrockAgentCore::GatewayTarget")

    by_name = {}
    for res in targets.values():
        props = res["Properties"]
        name = props["Name"]
        tools = props["TargetConfiguration"]["Mcp"]["Lambda"]["ToolSchema"]["InlinePayload"]
        by_name[name] = {t["Name"] for t in tools}

    assert set(by_name) == set(_TARGET_NAMES.values())
    for svc, target_name in _TARGET_NAMES.items():
        expected = {t["name"] for t in tool_schemas.tools_for_service(svc)}
        assert by_name[target_name] == expected


def test_all_25_tools_present_across_targets():
    tmpl = _template()
    targets = tmpl.find_resources("AWS::BedrockAgentCore::GatewayTarget")
    all_names = set()
    for res in targets.values():
        tools = res["Properties"]["TargetConfiguration"]["Mcp"]["Lambda"]["ToolSchema"][
            "InlinePayload"
        ]
        all_names |= {t["Name"] for t in tools}
    assert all_names == set(tool_schemas.BY_NAME)
    assert len(all_names) == 25


def test_gateway_role_invokes_exactly_four_lambda_arns():
    tmpl = _template()
    policies = tmpl.find_resources("AWS::IAM::Policy")
    invoke_statements = []
    for policy in policies.values():
        for stmt in policy["Properties"]["PolicyDocument"]["Statement"]:
            actions = stmt["Action"] if isinstance(stmt["Action"], list) else [stmt["Action"]]
            if "lambda:InvokeFunction" in actions:
                invoke_statements.append(stmt)
    assert invoke_statements, "expected a lambda:InvokeFunction statement on the gateway role"
    # The four target Lambda ARNs arrive by cross-stack reference (Fn::ImportValue
    # of the producing stacks' auto-generated export). Assert exactly four.
    resources = []
    for stmt in invoke_statements:
        res = stmt["Resource"]
        resources.extend(res if isinstance(res, list) else [res])
    assert len(resources) == 4
    for res in resources:
        assert "Fn::ImportValue" in _dumps(res)


def test_each_mock_stack_gets_one_gateway_invoke_permission():
    # fn.add_permission() lands the resource-based permission in the PRODUCING
    # (mock) stack, so each of the four mock stacks gains exactly one gateway
    # invoke permission (Task 3 source stays frozen; this is pure CDK wiring).
    _gw, mock_tmpls = _build()
    for svc, tmpl in mock_tmpls.items():
        perms = tmpl.find_resources("AWS::Lambda::Permission")
        gateway_perms = [
            p
            for p in perms.values()
            if p["Properties"].get("Principal") == "bedrock-agentcore.amazonaws.com"
        ]
        assert len(gateway_perms) == 1, f"{svc}: expected one gateway invoke permission"
        assert gateway_perms[0]["Properties"]["Action"] == "lambda:InvokeFunction"


def test_no_handwritten_named_import():
    # The design forbids importing the Task-3 NAMED outputs (JiraArn, etc.) by
    # name. CDK's auto-wired cross-stack reference uses generated export names, so
    # none of the four human-facing output names may appear in an ImportValue.
    tmpl = _template()
    body = _dumps(tmpl.to_json())
    for named in ("JiraArn", "ConfluenceArn", "GithubArn", "ServiceNowArn"):
        assert f'"Fn::ImportValue": "{named}"' not in body
        assert f'ImportValue":"{named}"' not in body


def _dumps(obj):
    import json

    return json.dumps(obj)
