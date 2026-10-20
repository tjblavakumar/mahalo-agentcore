"""AgentCore Runtime hosting the mahalo Strands agent (Task 6, design §E.1).

``MahaloRuntimeStack`` provisions the L2 ``agentcore.Runtime`` (jsii
``aws-cdk-lib.aws_bedrockagentcore.Runtime``) that hosts the ``agent/`` container,
plus its ``add_endpoint("default")`` endpoint. The L2 auto-creates the execution
role (ECR pull on the asset path, CloudWatch Logs, X-Ray); this stack adds only
the application-level grants (Bedrock model, Memory, Gateway) onto ``runtime.role``.

Offline-safety (the automated gate, §E.4): the artifact branch is flag-gated so
``cdk synth`` never invokes Docker. The default/offline branch uses
``AgentRuntimeArtifact.from_image_uri(CfnParameter.value_as_string)`` (the L2
factory the docstring designates for CloudFormation-parameter image URIs), which
constructs NO ``DockerImageAsset``. The operator-deploy branch
(``-c buildImage=1`` / ``MAHALO_BUILD_IMAGE=1``) uses ``from_asset`` to build +
push the ARM64 image.

Inbound auth: AWS_IAM/SigV4 is the L2 default (``authorizer_configuration``
omitted). A Cognito branch stub is left for the dev-mode upgrade.
"""

from __future__ import annotations

import os

from aws_cdk import CfnOutput, CfnParameter, Duration, Stack
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_iam as iam
from constructs import Construct

# Repo root relative to this file (…/infra-cdk/mahalo_infra/runtime_stack.py).
_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

_RUNTIME_NAME = "mahalo_agent_runtime"
_PLACEHOLDER_IMAGE = "000000000000.dkr.ecr.us-east-1.amazonaws.com/placeholder:latest"


class MahaloRuntimeStack(Stack):
    """L2 AgentCore Runtime (container) + endpoint + app-level role grants."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        memory_stack: "Stack",
        gateway_stack: "Stack | None" = None,
        model_id: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        tool_mode: str = "direct",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- (1) Runtime artifact — flag-gated so synth stays Docker-free. ---
        build_image = bool(self.node.try_get_context("buildImage")) or (
            os.environ.get("MAHALO_BUILD_IMAGE") == "1"
        )
        used_image_uri_branch = not build_image
        if build_image:
            # Operator deploy: build the ARM64 image from agent/Dockerfile and
            # push to ECR (this path invokes Docker during synth).
            artifact = agentcore.AgentRuntimeArtifact.from_asset(
                _REPO_ROOT,
                file="agent/Dockerfile",
                platform=ecr_assets.Platform.LINUX_ARM64,
            )
        else:
            # Offline gate: a CloudFormation-parameter image URI — NO DockerImageAsset.
            image_uri = CfnParameter(
                self,
                "AgentImageUri",
                type="String",
                default=_PLACEHOLDER_IMAGE,
                description="ECR image URI for the agent Runtime container.",
            ).value_as_string
            artifact = agentcore.AgentRuntimeArtifact.from_image_uri(image_uri)

        # --- (2) Env vars injected into the agent process (§E.3). ---
        environment = self._environment(memory_stack, gateway_stack, model_id, tool_mode)

        # --- (3) Inbound auth: AWS_IAM default; Cognito is the dev-mode upgrade. ---
        inbound = self.node.try_get_context("inboundAuth") or "AWS_IAM"
        authorizer = None  # None -> L2 default RuntimeAuthorizerConfiguration.iam()
        if inbound == "COGNITO":
            # Dev-mode upgrade stub: provide a user pool + client when enabling.
            raise NotImplementedError(
                "Cognito inbound auth is the dev-mode upgrade; wire a user pool "
                "and call RuntimeAuthorizerConfiguration.using_cognito(...) here."
            )

        runtime = agentcore.Runtime(
            self,
            "MahaloRuntime",
            runtime_name=_RUNTIME_NAME,
            agent_runtime_artifact=artifact,
            environment_variables=environment,
            authorizer_configuration=authorizer,
            tracing_enabled=True,
            lifecycle_configuration=agentcore.LifecycleConfiguration(
                idle_runtime_session_timeout=Duration.minutes(15),
                max_lifetime=Duration.hours(8),
            ),
        )

        # --- (4) App-level grants onto the auto-created execution role. ---
        self._grant_app_permissions(runtime, memory_stack, gateway_stack)
        if used_image_uri_branch:
            # from_image_uri grants NO IAM; add explicit ECR pull so a
            # parameter-supplied image can start (§E.1 / Finding 2).
            self._grant_ecr_pull(runtime)

        # --- (5) Endpoint + output for the thin API. ---
        runtime.add_endpoint("default")
        CfnOutput(self, "RuntimeArn", value=runtime.agent_runtime_arn)

        self.runtime = runtime

    # ------------------------------------------------------------------ #

    def _environment(self, memory_stack, gateway_stack, model_id, tool_mode) -> dict:
        """Build the Runtime env-var map. AWS_PROFILE is deliberately NOT set."""
        env = {
            "MAHALO_TOOL_MODE": tool_mode,
            "MAHALO_MEMORY_ENABLED": "true",
            "MAHALO_MEMORY_ID": memory_stack.memory.attr_memory_id,
            # Identity OFF for the AWS_IAM MVP (§D.4); flip to "true" on enablement.
            "MAHALO_IDENTITY_ENABLED": "false",
            "MAHALO_IDENTITY_JIRA_PROVIDER": "mahalo-jira-apikey",
            "BEDROCK_MODEL_ID": model_id,
            "AWS_REGION": self.region,
            # The four mock service base URLs (operator overrides at deploy).
            "JIRA_URL": "http://localhost:5001",
            "CONFLUENCE_URL": "http://localhost:5002",
            "GITHUB_URL": "http://localhost:5003",
            "SERVICENOW_URL": "http://localhost:5004",
        }
        if gateway_stack is not None:
            env["MAHALO_GATEWAY_MCP_URL"] = gateway_stack.gateway.attr_gateway_url
        return env

    def _grant_app_permissions(self, runtime, memory_stack, gateway_stack) -> None:
        """Bedrock model + Memory (+ Gateway in GATEWAY mode) on the exec role."""
        # Bedrock model invoke for Claude Sonnet 4.5 (inference profile + the
        # regional foundation-model ARNs the cross-region profile fans out to).
        runtime.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                resources=[
                    f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/"
                    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
                    "arn:aws:bedrock:*::foundation-model/"
                    "anthropic.claude-sonnet-4-5-20250929-v1:0",
                ],
            )
        )
        # AgentCore Memory STM read/write, scoped to the CfnMemory ARN.
        runtime.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock-agentcore:CreateEvent",
                    "bedrock-agentcore:ListEvents",
                    "bedrock-agentcore:GetEvent",
                    "bedrock-agentcore:RetrieveMemoryRecords",
                ],
                resources=[
                    memory_stack.memory.attr_memory_arn,
                    f"{memory_stack.memory.attr_memory_arn}/*",
                ],
            )
        )
        # AgentCore Gateway invoke (GATEWAY mode only).
        if gateway_stack is not None:
            runtime.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["bedrock-agentcore:InvokeGateway"],
                    resources=[gateway_stack.gateway.attr_gateway_arn],
                )
            )

    def _grant_ecr_pull(self, runtime) -> None:
        """Explicit ECR pull for the from_image_uri branch (grants no IAM itself)."""
        runtime.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ecr:GetAuthorizationToken"],
                resources=["*"],
            )
        )
        runtime.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:BatchGetImage",
                    "ecr:GetDownloadUrlForLayer",
                ],
                resources=[
                    f"arn:aws:ecr:{self.region}:{self.account}:repository/*",
                ],
            )
        )
