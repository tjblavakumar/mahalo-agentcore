"""DynamoDB table backing the shared skill library (skills design, section A).

``MahaloSkillsStack`` owns one on-demand DynamoDB table ``mahalo-skills`` with
partition key ``libraryId`` (the shared library is the single value ``common``)
and sort key ``skillName``. Mirrors ``MahaloModelConfigStack`` conventions
(PAY_PER_REQUEST billing, ``RemovalPolicy.DESTROY``). The table is exposed as
``self.table`` so ``MahaloApiStack`` can wire the env var + IAM grant by direct
construct reference (no ``Fn.import_value``).
"""

from aws_cdk import (
    CfnOutput,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_dynamodb as dynamodb
from constructs import Construct


class MahaloSkillsStack(Stack):
    """One DynamoDB table persisting uploaded skill files."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        table = dynamodb.Table(
            self,
            "Table",
            table_name="mahalo-skills",
            partition_key=dynamodb.Attribute(
                name="libraryId", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="skillName", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        CfnOutput(self, "SkillsTableName", value=table.table_name)

        self.table = table
