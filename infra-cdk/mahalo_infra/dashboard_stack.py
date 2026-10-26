"""DynamoDB table backing the custom dashboard (design §6).

``MahaloDashboardStack`` owns one on-demand DynamoDB table ``mahalo-dashboards``
partitioned on ``personaId`` (no sort key — each persona is a single item,
overwrite-save). Mirrors the ``MockServiceStack`` table conventions
(PAY_PER_REQUEST billing, ``RemovalPolicy.DESTROY`` for clean monthly-reset
teardown). The table is exposed as ``self.table`` so ``MahaloApiStack`` can wire
the env var + IAM grant by direct construct reference (no ``Fn.import_value``).
"""

from aws_cdk import (
    CfnOutput,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_dynamodb as dynamodb
from constructs import Construct


class MahaloDashboardStack(Stack):
    """One DynamoDB table persisting per-persona custom dashboards."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        table = dynamodb.Table(
            self,
            "Table",
            table_name="mahalo-dashboards",
            partition_key=dynamodb.Attribute(
                name="personaId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        CfnOutput(self, "DashboardTableName", value=table.table_name)

        self.table = table
