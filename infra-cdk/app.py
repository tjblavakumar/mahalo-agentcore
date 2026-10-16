#!/usr/bin/env python
"""CDK app: four per-service mock Lambda stacks.

Run ``cdk synth --all`` (offline, no AWS creds) to produce four CloudFormation
templates, or ``cdk deploy --all --profile lava`` to provision them. Each stack is
a ``MockServiceStack`` for one of jira/confluence/github/servicenow.
"""

import aws_cdk as cdk

from mahalo_infra.mock_service_stack import MockServiceStack

# Account / region per the approved design (Decision 4).
_ENV = cdk.Environment(account="051570254217", region="us-east-1")

_SERVICES = ("jira", "confluence", "github", "servicenow")


def main() -> None:
    app = cdk.App()
    for service in _SERVICES:
        stack_id = f"MahaloMock{service.capitalize()}Stack"
        MockServiceStack(
            app,
            stack_id,
            service=service,
            env=_ENV,
        )
    app.synth()


if __name__ == "__main__":
    main()
