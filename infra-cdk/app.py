#!/usr/bin/env python
"""CDK app: four per-service mock Lambda stacks.

Run ``cdk synth --all`` (offline, no AWS creds) to produce four CloudFormation
templates, or ``cdk deploy --all --profile lava`` to provision them. Each stack is
a ``MockServiceStack`` for one of jira/confluence/github/servicenow.
"""

import aws_cdk as cdk

from mahalo_infra.api_stack import MahaloApiStack
from mahalo_infra.gateway_stack import MahaloGatewayStack
from mahalo_infra.memory_identity_stack import MahaloMemoryIdentityStack
from mahalo_infra.mock_service_stack import MockServiceStack
from mahalo_infra.runtime_stack import MahaloRuntimeStack

# Account / region per the approved design (Decision 4).
_ENV = cdk.Environment(account="<AWS_ACCOUNT_ID>", region="us-east-1")

_SERVICES = ("jira", "confluence", "github", "servicenow")


def main() -> None:
    app = cdk.App()
    mock_stacks = {}
    for service in _SERVICES:
        stack_id = f"MahaloMock{service.capitalize()}Stack"
        mock_stacks[service] = MockServiceStack(
            app,
            stack_id,
            service=service,
            env=_ENV,
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
    MahaloApiStack(
        app,
        "MahaloApiStack",
        runtime_stack=runtime_stack,
        env=_ENV,
    )
    app.synth()


if __name__ == "__main__":
    main()
