"""App-level synth assertion (Task 7b): the full app produces exactly 11 stacks.

After wiring MahaloBuilderStack, ``cdk synth --all`` must emit 11 templates: the
4 mock stacks + Gateway + MemoryIdentity + Runtime + Api + Gitea + Frontend +
Builder. This guards the stale 'stays 10' count from regressing.
"""

import aws_cdk as cdk

from mahalo_infra.api_stack import MahaloApiStack
from mahalo_infra.builder_stack import MahaloBuilderStack
from mahalo_infra.frontend_stack import MahaloFrontendStack
from mahalo_infra.gateway_stack import MahaloGatewayStack
from mahalo_infra.gitea_stack import MahaloGiteaStack
from mahalo_infra.memory_identity_stack import MahaloMemoryIdentityStack
from mahalo_infra.mock_service_stack import MockServiceStack
from mahalo_infra.runtime_stack import MahaloRuntimeStack

_ENV = cdk.Environment(account="<AWS_ACCOUNT_ID>", region="us-east-1")
_SERVICES = ("jira", "confluence", "github", "servicenow")


def test_app_synthesizes_eleven_stacks():
    app = cdk.App()
    mock_stacks = {
        service: MockServiceStack(
            app,
            f"MahaloMock{service.capitalize()}Stack",
            service=service,
            env=_ENV,
        )
        for service in _SERVICES
    }
    MahaloGatewayStack(app, "MahaloGatewayStack", mock_stacks=mock_stacks, env=_ENV)
    memory_identity = MahaloMemoryIdentityStack(
        app, "MahaloMemoryIdentityStack", env=_ENV
    )
    runtime_stack = MahaloRuntimeStack(
        app, "MahaloRuntimeStack", memory_stack=memory_identity, env=_ENV
    )
    api_stack = MahaloApiStack(
        app, "MahaloApiStack", runtime_stack=runtime_stack, env=_ENV
    )
    MahaloGiteaStack(app, "MahaloGiteaStack", env=_ENV)
    MahaloFrontendStack(app, "MahaloFrontendStack", api_stack=api_stack, env=_ENV)
    MahaloBuilderStack(app, "MahaloBuilderStack", env=_ENV)

    assert len(app.synth().stacks) == 11
