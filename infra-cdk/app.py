#!/usr/bin/env python
"""CDK app: four per-service mock Lambda stacks.

Run ``cdk synth --all`` (offline, no AWS creds) to produce four CloudFormation
templates, or ``cdk deploy --all --profile lava`` to provision them. Each stack is
a ``MockServiceStack`` for one of jira/confluence/github/servicenow.
"""

import os

import aws_cdk as cdk

from mahalo_infra.api_stack import MahaloApiStack
from mahalo_infra.builder_stack import MahaloBuilderStack
from mahalo_infra.dashboard_stack import MahaloDashboardStack
from mahalo_infra.frontend_stack import MahaloFrontendStack
from mahalo_infra.gateway_stack import MahaloGatewayStack
from mahalo_infra.gitea_stack import MahaloGiteaStack
from mahalo_infra.memory_identity_stack import MahaloMemoryIdentityStack
from mahalo_infra.mock_service_stack import MockServiceStack
from mahalo_infra.runtime_stack import MahaloRuntimeStack

# Account / region. The account is taken from the environment (CDK sets
# CDK_DEFAULT_ACCOUNT from the caller's credentials at synth/deploy; AWS_ACCOUNT_ID
# is an accepted override) so no real account id is committed to source. Region
# defaults to us-east-1 and can be overridden via CDK_DEFAULT_REGION/AWS_REGION.
_ACCOUNT = (
    os.environ.get("CDK_DEFAULT_ACCOUNT")
    or os.environ.get("AWS_ACCOUNT_ID")
)
_REGION = (
    os.environ.get("CDK_DEFAULT_REGION")
    or os.environ.get("AWS_REGION")
    or "us-east-1"
)
_ENV = cdk.Environment(account=_ACCOUNT, region=_REGION)

_SERVICES = ("jira", "confluence", "github", "servicenow")

# Gitea env + SSM token param name injected into the github mock Lambda ONLY when
# ``-c giteaMode=real`` (design Â§C.4b). The values are non-secret references; the
# token itself is resolved at Lambda cold start from the SSM SecureString named
# here. Kept as module-level constants so app.py reads them once.
_GITEA_TOKEN_PARAM = "/mahalo/gitea/adapter-token"
_GITEA_ENV = {
    "GITEA_URL": "https://d3ec76atxiij9a.cloudfront.net",
    "GITEA_ADMIN_USER": "mahalo_admin",
    "GITEA_PUBLIC_URL": "https://d3ec76atxiij9a.cloudfront.net",
    "DEMO_DEVELOPER_ID": "dev-6",
    "GITEA_TOKEN_PARAM": _GITEA_TOKEN_PARAM,
}


def main() -> None:
    app = cdk.App()
    # Flipped on by ``-c giteaMode=real``; default off -> all four mock stacks
    # synth byte-identical to Task 6.
    gitea_mode = app.node.try_get_context("giteaMode") == "real"
    mock_stacks = {}
    for service in _SERVICES:
        stack_id = f"MahaloMock{service.capitalize()}Stack"
        mock_stacks[service] = MockServiceStack(
            app,
            stack_id,
            service=service,
            env=_ENV,
            gitea_mode=(gitea_mode if service == "github" else False),
            gitea_env=(_GITEA_ENV if service == "github" else None),
            gitea_token_param_name=(
                _GITEA_TOKEN_PARAM if service == "github" else None
            ),
        )
    # Task 4: the Gateway stack fronts the four mock Lambdas (ARNs by direct
    # construct reference; CDK auto-orders the deploy via the implicit dependency).
    gateway_stack = MahaloGatewayStack(
        app,
        "MahaloGatewayStack",
        mock_stacks=mock_stacks,
        env=_ENV,
    )
    # Task 5: AgentCore Memory (STM) + Identity. Independent of the mock/gateway
    # stacks (no cross-references), so synth ordering is unaffected.
    memory_identity = MahaloMemoryIdentityStack(
        app,
        "MahaloMemoryIdentityStack",
        env=_ENV,
    )
    # Task 6: Runtime hosting the Strands agent (L2 agentcore.Runtime) + the thin
    # API Function-URL Lambda. Direct construct references (no Fn.import_value),
    # mirroring how the gateway/memory stacks are wired.
    # GATEWAY tool mode (the intended production path): the hosted agent reaches
    # the four mock Lambdas through the deployed AgentCore Gateway over MCP, so
    # _environment sets MAHALO_GATEWAY_MCP_URL from gateway_stack. (DIRECT mode's
    # localhost:500x mock URLs do not exist inside the Runtime container.)
    runtime_stack = MahaloRuntimeStack(
        app,
        "MahaloRuntimeStack",
        memory_stack=memory_identity,
        gateway_stack=gateway_stack,
        tool_mode="gateway",
        env=_ENV,
    )
    # Custom dashboard persistence table (design §6). Constructed BEFORE the API
    # stack and wired in by direct construct reference (no Fn.import_value).
    dashboard_stack = MahaloDashboardStack(
        app,
        "MahaloDashboardStack",
        env=_ENV,
    )
    api_stack = MahaloApiStack(
        app,
        "MahaloApiStack",
        runtime_stack=runtime_stack,
        dashboard_stack=dashboard_stack,
        env=_ENV,
    )
    # Task 7: always-on Gitea host for the real github backend, and the static
    # frontend hosting. Task 7c removed the Cognito identity pool, so the frontend
    # stack no longer references the API (the Function URL is AuthType=NONE); it
    # takes no api_stack parameter.
    MahaloGiteaStack(app, "MahaloGiteaStack", env=_ENV)
    MahaloFrontendStack(
        app,
        "MahaloFrontendStack",
        env=_ENV,
    )
    # Task 7b: transient arm64 AL2023 EC2 builder host for the Docker-dependent
    # build/deploy steps the WorkSpaces VDI cannot run. Standalone (no
    # cross-references), mirroring the other independent stacks.
    MahaloBuilderStack(app, "MahaloBuilderStack", env=_ENV)
    app.synth()


if __name__ == "__main__":
    main()
