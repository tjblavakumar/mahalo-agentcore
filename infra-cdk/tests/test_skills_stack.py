"""CDK synth assertion tests for MahaloSkillsStack, offline.

The skills stack owns one on-demand DynamoDB table ``mahalo-skills`` keyed on
``libraryId`` (HASH) + ``skillName`` (RANGE), DeletionPolicy Delete. The API
wiring (env var, grant, DELETE CORS) is asserted in test_api_stack.py.
"""

import aws_cdk as cdk
from aws_cdk import assertions

from mahalo_infra.skills_stack import MahaloSkillsStack

_ENV = cdk.Environment(account="123456789012", region="us-east-1")


def _skills_template():
    app = cdk.App()
    stack = MahaloSkillsStack(app, "MahaloSkillsStack", env=_ENV)
    return assertions.Template.from_stack(stack)


def test_single_dynamodb_table_on_library_and_skill_name():
    tmpl = _skills_template()
    tmpl.resource_count_is("AWS::DynamoDB::Table", 1)
    tmpl.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "BillingMode": "PAY_PER_REQUEST",
            "KeySchema": [
                {"AttributeName": "libraryId", "KeyType": "HASH"},
                {"AttributeName": "skillName", "KeyType": "RANGE"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "libraryId", "AttributeType": "S"},
                {"AttributeName": "skillName", "AttributeType": "S"},
            ],
            "TableName": "mahalo-skills",
        },
    )


def test_table_deletion_policy_delete():
    tmpl = _skills_template()
    (table,) = tmpl.find_resources("AWS::DynamoDB::Table").values()
    assert table["DeletionPolicy"] == "Delete"


def test_skills_table_output():
    tmpl = _skills_template()
    assert "SkillsTableName" in tmpl.to_json().get("Outputs", {})
