"""AgentCore Gateway + four Lambda MCP targets (Task 4, Decision D).

``MahaloGatewayStack`` fronts the four Task-3 mock Lambdas with one Amazon
Bedrock AgentCore Gateway and exposes their operations as MCP tools. It uses the
native, stable L1 constructs in ``aws_cdk.aws_bedrockagentcore`` (``CfnGateway``
+ ``CfnGatewayTarget``) from the installed ``aws-cdk-lib``.

The four Lambda ARNs arrive by DIRECT construct reference — ``app.py`` passes the
four ``MockServiceStack`` instances in — so CDK auto-wires the cross-stack
reference and an implicit dependency, and ``mock_service_stack.py`` stays frozen
(no ``Fn.import_value``).

Each target's ``toolSchema.inlinePayload`` is generated from the single source of
truth ``common.tool_schemas`` (also read by the Lambda adapter) so the published
schema and the adapter arg-mapping cannot drift. Inbound auth is the
``authorizerType`` CfnParameter (default ``AWS_IAM``); outbound Gateway->Lambda
uses ``GATEWAY_IAM_ROLE``.
"""

from __future__ import annotations

import os
import sys
from typing import Dict, List

from aws_cdk import CfnOutput, CfnParameter, Stack
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_iam as iam
from constructs import Construct

# Make ``common.tool_schemas`` importable (the single source of truth lives under
# ../tools-lambdas, packaged as the top-level ``common`` package in each Lambda).
_TOOLS_LAMBDAS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "tools-lambdas",
)
if _TOOLS_LAMBDAS_DIR not in sys.path:
    sys.path.append(_TOOLS_LAMBDAS_DIR)

from common import tool_schemas  # noqa: E402

_GATEWAY_PRINCIPAL = "bedrock-agentcore.amazonaws.com"

# service -> Gateway target name ("mock-<svc>").
_TARGET_NAMES = {
    "jira": "mock-jira",
    "confluence": "mock-confluence",
    "github": "mock-github",
    "servicenow": "mock-servicenow",
}


def _schema_to_cfn(schema: Dict) -> agentcore.CfnGatewayTarget.SchemaDefinitionProperty:
    """Recursively map a JSON-Schema-subset dict to a ``SchemaDefinitionProperty``."""
    properties = None
    if schema.get("properties"):
        properties = {
            name: _schema_to_cfn(prop) for name, prop in schema["properties"].items()
        }
    items = None
    if schema.get("items"):
        items = _schema_to_cfn(schema["items"])
    return agentcore.CfnGatewayTarget.SchemaDefinitionProperty(
        type=schema["type"],
        description=schema.get("description"),
        properties=properties,
        items=items,
        required=schema.get("required"),
    )


def _tool_definitions(service: str) -> List[agentcore.CfnGatewayTarget.ToolDefinitionProperty]:
    """Build the ``ToolDefinition`` list for one service from ``tool_schemas``."""
    definitions = []
    for descriptor in tool_schemas.tools_for_service(service):
        definitions.append(
            agentcore.CfnGatewayTarget.ToolDefinitionProperty(
                name=descriptor["name"],
                description=descriptor["description"],
                input_schema=_schema_to_cfn(descriptor["input_schema"]),
            )
        )
    return definitions


class MahaloGatewayStack(Stack):
    """One AgentCore Gateway fronting the four mock-service Lambdas as MCP tools."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        mock_stacks: Dict[str, "Stack"],
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        missing = set(_TARGET_NAMES) - set(mock_stacks)
        if missing:
            raise ValueError(f"Missing mock stacks for: {sorted(missing)}")

        authorizer_type = CfnParameter(
            self,
            "AuthorizerType",
            type="String",
            default="AWS_IAM",
            allowed_values=["AWS_IAM", "CUSTOM_JWT", "AUTHENTICATE_ONLY", "NONE"],
            description="Inbound authorizer for the Gateway (default AWS_IAM).",
        )

        function_arns = [
            mock_stacks[svc].function.function_arn for svc in _TARGET_NAMES
        ]

        # (1) Gateway IAM service role: trust the AgentCore service, allow invoking
        # only the four target Lambdas (least privilege).
        role = iam.Role(
            self,
            "GatewayRole",
            assumed_by=iam.ServicePrincipal(_GATEWAY_PRINCIPAL),
            description="AgentCore Gateway service role for the mahalo mock targets",
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=function_arns,
            )
        )

        # (2) The Gateway (MCP protocol, parameterized inbound auth).
        gateway = agentcore.CfnGateway(
            self,
            "Gateway",
            name="mahalo-gateway",
            protocol_type="MCP",
            role_arn=role.role_arn,
            authorizer_type=authorizer_type.value_as_string,
            protocol_configuration=agentcore.CfnGateway.GatewayProtocolConfigurationProperty(
                mcp=agentcore.CfnGateway.MCPGatewayConfigurationProperty(
                    supported_versions=["2025-03-26"],
                ),
            ),
        )

        # (3) Four Lambda targets, each carrying its service's inline toolSchema,
        # invoked via the Gateway's own IAM role.
        for svc, target_name in _TARGET_NAMES.items():
            fn = mock_stacks[svc].function
            target = agentcore.CfnGatewayTarget(
                self,
                f"{svc.capitalize()}Target",
                gateway_identifier=gateway.attr_gateway_identifier,
                name=target_name,
                target_configuration=agentcore.CfnGatewayTarget.TargetConfigurationProperty(
                    mcp=agentcore.CfnGatewayTarget.McpTargetConfigurationProperty(
                        lambda_=agentcore.CfnGatewayTarget.McpLambdaTargetConfigurationProperty(
                            lambda_arn=fn.function_arn,
                            tool_schema=agentcore.CfnGatewayTarget.ToolSchemaProperty(
                                inline_payload=_tool_definitions(svc),
                            ),
                        ),
                    ),
                ),
                credential_provider_configurations=[
                    agentcore.CfnGatewayTarget.CredentialProviderConfigurationProperty(
                        credential_provider_type="GATEWAY_IAM_ROLE",
                    )
                ],
            )
            target.add_dependency(gateway)

            # (4) Allow the Gateway service principal to invoke this Lambda.
            fn.add_permission(
                f"GatewayInvoke{svc.capitalize()}",
                principal=iam.ServicePrincipal(_GATEWAY_PRINCIPAL),
                action="lambda:InvokeFunction",
            )

        # (5) Outputs so the operator can point the agent at the Gateway.
        CfnOutput(self, "GatewayId", value=gateway.attr_gateway_identifier)
        CfnOutput(self, "GatewayArn", value=gateway.attr_gateway_arn)
        CfnOutput(self, "GatewayMcpUrl", value=gateway.attr_gateway_url)

        self.gateway = gateway
        self.role = role
