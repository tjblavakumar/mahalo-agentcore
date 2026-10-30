"""App-level synth assertion: the full app produces exactly 13 stacks.

After wiring MahaloKeepWarmStack (latency follow-up #3), ``cdk synth --all`` must
emit 13 templates: the 4 mock stacks + Gateway + MemoryIdentity + Runtime +
Dashboard + Api + KeepWarm + Gitea + Frontend + Builder. This guards the count
from regressing.
"""

import aws_cdk as cdk

from mahalo_infra.api_stack import MahaloApiStack
from mahalo_infra.builder_stack import MahaloBuilderStack
from mahalo_infra.dashboard_stack import MahaloDashboardStack
from mahalo_infra.frontend_stack import MahaloFrontendStack
from mahalo_infra.gateway_stack import MahaloGatewayStack
from mahalo_infra.gitea_stack import MahaloGiteaStack
from mahalo_infra.keepwarm_stack import MahaloKeepWarmStack
from mahalo_infra.memory_identity_stack import MahaloMemoryIdentityStack
from mahalo_infra.mock_service_stack import MockServiceStack
from mahalo_infra.runtime_stack import MahaloRuntimeStack

_ENV = cdk.Environment(account="123456789012", region="us-east-1")
_SERVICES = ("jira", "confluence", "github", "servicenow")


def test_app_synthesizes_thirteen_stacks():
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
    dashboard_stack = MahaloDashboardStack(app, "MahaloDashboardStack", env=_ENV)
    api_stack = MahaloApiStack(
        app,
        "MahaloApiStack",
        runtime_stack=runtime_stack,
        dashboard_stack=dashboard_stack,
        env=_ENV,
    )
    MahaloKeepWarmStack(
        app, "MahaloKeepWarmStack", runtime_stack=runtime_stack, env=_ENV
    )
    MahaloGiteaStack(app, "MahaloGiteaStack", env=_ENV)
    MahaloFrontendStack(app, "MahaloFrontendStack", env=_ENV)
    MahaloBuilderStack(app, "MahaloBuilderStack", env=_ENV)

    assert len(app.synth().stacks) == 13
