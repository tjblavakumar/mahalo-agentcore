#!/usr/bin/env python
"""CDK app: four per-service mock Lambda stacks.

Run ``cdk synth --all`` (offline, no AWS creds) to produce four CloudFormation
templates, or ``cdk deploy --all --profile lava`` to provision them. Each stack is
a ``MockServiceStack`` for one of jira/confluence/github/servicenow.
"""

import aws_cdk as cdk

from mahalo_infra.api_stack import MahaloApiStack
from mahalo_infra.frontend_stack import MahaloFrontendStack
from mahalo_infra.gateway_stack import MahaloGatewayStack
from mahalo_infra.gitea_stack import MahaloGiteaStack
from mahalo_infra.memory_identity_stack import MahaloMemoryIdentityStack
from mahalo_infra.mock_service_stack import MockServiceStack
from mahalo_infra.runtime_stack import MahaloRuntimeStack

# Account / region per the approved design (Decision 4).
_ENV = cdk.Environment(account="<AWS_ACCOUNT_ID>", region="us-east-1")

_SERVICES = ("jira", "confluence", "github", "servicenow")

# Gitea env + SSM token param name injected into the github mock Lambda ONLY when
# ``-c giteaMode=real`` (design §C.4b). The values are non-secret references; the
# token itself is resolved at Lambda cold start from the SSM SecureString named
# here. Kept as module-level constants so app.py reads them once.
_GITEA_TOKEN_PARAM = "/mahalo/gitea/adapter-token"
_GITEA_ENV = {
    "GITEA_URL": "http://gitea.internal:3000",
    "GITEA_ADMIN_USER": "mahalo_admin",
    "GITEA_PUBLIC_URL": "http://gitea.public:3000",
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
    MahaloGatewayStack(
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
    # mirroring how the gateway/memory stacks are wired. DIRECT tool mode by
    # default so no gateway cross-reference is required for the offline gate.
    runtime_stack = MahaloRuntimeStack(
        app,
        "MahaloRuntimeStack",
        memory_stack=memory_identity,
        env=_ENV,
    )
    api_stack = MahaloApiStack(
        app,
        "MahaloApiStack",
        runtime_stack=runtime_stack,
        env=_ENV,
    )
    # Task 7: always-on Gitea host for the real github backend, and the static
    # frontend hosting + browser auth. Direct construct references (no
    # Fn.import_value); the frontend stack reads only api_stack.function.function_arn
    # for the unauthenticated role's lambda:InvokeFunctionUrl policy (§D.2/§E.1).
    MahaloGiteaStack(app, "MahaloGiteaStack", env=_ENV)
    MahaloFrontendStack(
        app,
        "MahaloFrontendStack",
        api_stack=api_stack,
        env=_ENV,
    )
    app.synth()


if __name__ == "__main__":
    main()
