"""CDK synth assertion tests for MahaloDashboardStack + its API wiring, offline.

The dashboard stack owns one on-demand DynamoDB table keyed on ``personaId``
(no sort key, DeletionPolicy Delete). When wired into MahaloApiStack the Lambda
gets ``MAHALO_DASHBOARD_TABLE`` in its env, a role with GetItem+PutItem on the
table, and a Function URL whose CORS AllowMethods includes PUT and GET.
"""

import aws_cdk as cdk
from aws_cdk import assertions

from mahalo_infra.api_stack import MahaloApiStack
from mahalo_infra.dashboard_stack import MahaloDashboardStack
from mahalo_infra.memory_identity_stack import MahaloMemoryIdentityStack
from mahalo_infra.runtime_stack import MahaloRuntimeStack

_ENV = cdk.Environment(account="123456789012", region="us-east-1")


def _dashboard_template():
    app = cdk.App()
    dashboard = MahaloDashboardStack(app, "MahaloDashboardStack", env=_ENV)
    return assertions.Template.from_stack(dashboard)


def _api_template_with_dashboard():
    app = cdk.App()
    memory = MahaloMemoryIdentityStack(app, "MahaloMemoryIdentityStack", env=_ENV)
    runtime = MahaloRuntimeStack(app, "MahaloRuntimeStack", memory_stack=memory, env=_ENV)
    dashboard = MahaloDashboardStack(app, "MahaloDashboardStack", env=_ENV)
    api = MahaloApiStack(
        app,
        "MahaloApiStack",
        runtime_stack=runtime,
        dashboard_stack=dashboard,
        env=_ENV,
    )
    return assertions.Template.from_stack(api)


def test_single_dynamodb_table_on_persona_id():
    tmpl = _dashboard_template()
    tmpl.resource_count_is("AWS::DynamoDB::Table", 1)
    tmpl.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "BillingMode": "PAY_PER_REQUEST",
            "KeySchema": [{"AttributeName": "personaId", "KeyType": "HASH"}],
            "TableName": "mahalo-dashboards",
        },
    )


def test_table_deletion_policy_delete():
    tmpl = _dashboard_template()
    tables = tmpl.find_resources("AWS::DynamoDB::Table")
    (table,) = tables.values()
    assert table["DeletionPolicy"] == "Delete"


def test_dashboard_table_output():
    tmpl = _dashboard_template()
    outputs = tmpl.to_json().get("Outputs", {})
    assert "DashboardTableName" in outputs


def test_api_lambda_has_dashboard_table_env():
    tmpl = _api_template_with_dashboard()
    fns = tmpl.find_resources("AWS::Lambda::Function")
    (fn,) = fns.values()
    env = fn["Properties"]["Environment"]["Variables"]
    assert "MAHALO_DASHBOARD_TABLE" in env


def test_api_role_can_read_write_dashboard_table():
    tmpl = _api_template_with_dashboard()
    policies = tmpl.find_resources("AWS::IAM::Policy")
    actions = set()
    for policy in policies.values():
        for stmt in policy["Properties"]["PolicyDocument"]["Statement"]:
            act = stmt["Action"]
            actions.update(act if isinstance(act, list) else [act])
    assert "dynamodb:GetItem" in actions
    assert "dynamodb:PutItem" in actions


def test_api_function_url_cors_allows_put_and_get():
    tmpl = _api_template_with_dashboard()
    urls = tmpl.find_resources("AWS::Lambda::Url")
    (url,) = urls.values()
    methods = set(url["Properties"]["Cors"]["AllowMethods"])
    assert "PUT" in methods
    assert "GET" in methods
