"""CDK synth assertion tests for MahaloModelConfigStack + its API wiring, offline.

The model-config stack owns one on-demand DynamoDB table keyed on ``personaId``
(no sort key, DeletionPolicy Delete). When wired into MahaloApiStack the Lambda
gets ``MAHALO_MODEL_CONFIG_TABLE`` in its env and a role with GetItem+PutItem on
the table — mirroring the dashboard table wiring.
"""

import aws_cdk as cdk
from aws_cdk import assertions

from mahalo_infra.api_stack import MahaloApiStack
from mahalo_infra.dashboard_stack import MahaloDashboardStack
from mahalo_infra.memory_identity_stack import MahaloMemoryIdentityStack
from mahalo_infra.model_config_stack import MahaloModelConfigStack
from mahalo_infra.runtime_stack import MahaloRuntimeStack

_ENV = cdk.Environment(account="123456789012", region="us-east-1")


def _model_config_template():
    app = cdk.App()
    stack = MahaloModelConfigStack(app, "MahaloModelConfigStack", env=_ENV)
    return assertions.Template.from_stack(stack)


def _api_template():
    app = cdk.App()
    memory = MahaloMemoryIdentityStack(app, "MahaloMemoryIdentityStack", env=_ENV)
    runtime = MahaloRuntimeStack(app, "MahaloRuntimeStack", memory_stack=memory, env=_ENV)
    dashboard = MahaloDashboardStack(app, "MahaloDashboardStack", env=_ENV)
    model_config = MahaloModelConfigStack(app, "MahaloModelConfigStack", env=_ENV)
    api = MahaloApiStack(
        app,
        "MahaloApiStack",
        runtime_stack=runtime,
        dashboard_stack=dashboard,
        model_config_stack=model_config,
        env=_ENV,
    )
    return assertions.Template.from_stack(api)


def test_single_dynamodb_table_on_persona_id():
    tmpl = _model_config_template()
    tmpl.resource_count_is("AWS::DynamoDB::Table", 1)
    tmpl.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "BillingMode": "PAY_PER_REQUEST",
            "KeySchema": [{"AttributeName": "personaId", "KeyType": "HASH"}],
            "TableName": "mahalo-model-config",
        },
    )


def test_table_deletion_policy_delete():
    tmpl = _model_config_template()
    tables = tmpl.find_resources("AWS::DynamoDB::Table")
    (table,) = tables.values()
    assert table["DeletionPolicy"] == "Delete"


def test_model_config_table_output():
    tmpl = _model_config_template()
    outputs = tmpl.to_json().get("Outputs", {})
    assert "ModelConfigTableName" in outputs


def test_api_lambda_has_model_config_table_env():
    tmpl = _api_template()
    fns = tmpl.find_resources("AWS::Lambda::Function")
    (fn,) = fns.values()
    env = fn["Properties"]["Environment"]["Variables"]
    assert "MAHALO_MODEL_CONFIG_TABLE" in env


def test_api_role_can_read_write_model_config_table():
    tmpl = _api_template()
    policies = tmpl.find_resources("AWS::IAM::Policy")
    actions = set()
    for policy in policies.values():
        for stmt in policy["Properties"]["PolicyDocument"]["Statement"]:
            act = stmt["Action"]
            actions.update(act if isinstance(act, list) else [act])
    assert "dynamodb:GetItem" in actions
    assert "dynamodb:PutItem" in actions
