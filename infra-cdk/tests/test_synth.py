"""CDK synth assertion tests for the four MockServiceStacks.

These run fully offline (no AWS creds). Each stack must synthesize exactly one
DynamoDB table (PAY_PER_REQUEST, pk/sk key schema), one python3.13 Lambda whose
handler is ``<svc>.handler.lambda_handler`` with a ``TABLE_NAME`` env var, one
Function URL with ``AuthType=NONE``, and an IAM policy scoped to that single table.
"""

import aws_cdk as cdk
import pytest
from aws_cdk import assertions

from mahalo_infra.mock_service_stack import MockServiceStack

_ENV = cdk.Environment(account="123456789012", region="us-east-1")

# service -> (table name, handler, token env key, token value)
_CASES = {
    "jira": (
        "mahalo-mock-jira",
        "jira.handler.lambda_handler",
        "MOCK_JIRA_TOKEN",
        "mock-jira-token-12345",
    ),
    "confluence": (
        "mahalo-mock-confluence",
        "confluence.handler.lambda_handler",
        "MOCK_CONFLUENCE_TOKEN",
        "mock-confluence-token-12345",
    ),
    "github": (
        "mahalo-mock-github",
        "github.handler.lambda_handler",
        "MOCK_GITHUB_TOKEN",
        "mock-github-token-12345",
    ),
    "servicenow": (
        "mahalo-mock-servicenow",
        "servicenow.handler.lambda_handler",
        "MOCK_SERVICENOW_TOKEN",
        "mock-servicenow-token-12345",
    ),
}


def _template(service: str) -> assertions.Template:
    app = cdk.App()
    stack = MockServiceStack(
        app,
        f"MahaloMock{service.capitalize()}Stack",
        service=service,
        env=_ENV,
    )
    return assertions.Template.from_stack(stack)


@pytest.fixture(params=sorted(_CASES), ids=sorted(_CASES))
def service(request):
    return request.param


def test_single_dynamodb_table(service):
    tmpl = _template(service)
    table_name, *_ = _CASES[service]
    tmpl.resource_count_is("AWS::DynamoDB::Table", 1)
    tmpl.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "TableName": table_name,
            "BillingMode": "PAY_PER_REQUEST",
            "KeySchema": [
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            "AttributeDefinitions": assertions.Match.array_with(
                [
                    {"AttributeName": "pk", "AttributeType": "S"},
                    {"AttributeName": "sk", "AttributeType": "S"},
                ]
            ),
        },
    )


def test_single_python313_lambda(service):
    tmpl = _template(service)
    _, handler, token_env, token_val = _CASES[service]
    tmpl.resource_count_is("AWS::Lambda::Function", 1)
    tmpl.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Runtime": "python3.13",
            "Handler": handler,
            "MemorySize": 256,
            "Timeout": 30,
            "Environment": {
                "Variables": assertions.Match.object_like(
                    {
                        "TABLE_NAME": _CASES[service][0],
                        token_env: token_val,
                    }
                )
            },
        },
    )


def test_function_url_auth_none(service):
    tmpl = _template(service)
    tmpl.resource_count_is("AWS::Lambda::Url", 1)
    tmpl.has_resource_properties(
        "AWS::Lambda::Url",
        {"AuthType": "NONE"},
    )


def test_cfn_outputs_url_and_arn(service):
    tmpl = _template(service)
    outputs = tmpl.find_outputs("*")
    # Exactly the URL + ARN outputs for this one service.
    assert len(outputs) == 2
    label = {
        "jira": "Jira",
        "confluence": "Confluence",
        "github": "Github",
        "servicenow": "ServiceNow",
    }[service]
    assert f"{label}Url" in outputs
    assert f"{label}Arn" in outputs


def test_iam_policy_scoped_to_single_table(service):
    tmpl = _template(service)
    # The Lambda's role gets exactly one inline policy (the grant_read_write_data
    # for this stack's own table). Assert it exists and references DynamoDB.
    tmpl.resource_count_is("AWS::IAM::Policy", 1)
    policies = tmpl.find_resources("AWS::IAM::Policy")
    (policy,) = policies.values()
    statements = policy["Properties"]["PolicyDocument"]["Statement"]
    dynamo_statements = [
        s
        for s in statements
        if any(
            str(action).startswith("dynamodb:")
            for action in (
                s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
            )
        )
    ]
    assert dynamo_statements, "expected a DynamoDB statement in the Lambda policy"
    # Every DynamoDB statement must resolve against this stack's single table
    # resource (least privilege: no wildcard table ARNs, no other table refs).
    table_logical_ids = set(tmpl.find_resources("AWS::DynamoDB::Table"))
    assert len(table_logical_ids) == 1
    (table_logical_id,) = table_logical_ids

    def _mentions_only_own_table(resource) -> bool:
        refs = _collect_fn_getatt_refs(resource)
        # Resources are the table ARN (Fn::GetAtt TABLE.Arn) and its index/arn
        # children expressed via Fn::Join on the same GetAtt; no other table.
        return refs and refs <= {table_logical_id}

    for stmt in dynamo_statements:
        assert _mentions_only_own_table(stmt["Resource"]), (
            "DynamoDB permission must be scoped to this stack's own table only"
        )


def _collect_fn_getatt_refs(node) -> set:
    """Collect logical ids referenced by Fn::GetAtt / Ref anywhere in node."""
    refs: set = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "Fn::GetAtt" and isinstance(value, list) and value:
                refs.add(value[0])
            elif key == "Ref" and isinstance(value, str):
                refs.add(value)
            else:
                refs |= _collect_fn_getatt_refs(value)
    elif isinstance(node, list):
        for item in node:
            refs |= _collect_fn_getatt_refs(item)
    return refs
