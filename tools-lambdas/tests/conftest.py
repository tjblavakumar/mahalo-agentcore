"""Shared pytest fixtures: moto DynamoDB table + synthetic event builders.

All tests run offline. ``@mock_aws`` fakes DynamoDB so no AWS credentials or
network access are required. Dummy credentials are forced into the environment
so botocore never tries to reach a real credential source.
"""

import json
import os
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

# Make ``common`` and each service package importable as top-level modules, the
# same way the Lambda asset exposes them (asset root on sys.path).
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch):
    """Force dummy AWS creds/region so no real credential lookup happens."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


def _create_table(name):
    client = boto3.client("dynamodb", region_name="us-east-1")
    client.create_table(
        TableName=name,
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    client.get_waiter("table_exists").wait(TableName=name)
    return name


@pytest.fixture
def dynamo_table():
    """Create a ``mahalo-mock-test`` table under moto; yield its name."""
    with mock_aws():
        name = "mahalo-mock-test"
        _create_table(name)
        yield name


def make_event(method, path, *, query=None, headers=None, body=None, token=None):
    """Build a Lambda Function URL v2 event."""
    hdrs = {k.lower(): v for k, v in (headers or {}).items()}
    if token is not None:
        hdrs["x-api-token"] = token
    raw_qs = ""
    if query:
        raw_qs = "&".join(f"{k}={v}" for k, v in query.items())
    event = {
        "version": "2.0",
        "rawPath": path,
        "rawQueryString": raw_qs,
        "headers": hdrs,
        "queryStringParameters": dict(query) if query else None,
        "requestContext": {"http": {"method": method, "path": path}},
        "isBase64Encoded": False,
    }
    if body is not None:
        event["body"] = body if isinstance(body, str) else json.dumps(body)
    return event


def make_apigw_event(method, path, *, query=None, headers=None, body=None, token=None):
    """Build an API-Gateway-shaped (top-level ``httpMethod``) event."""
    hdrs = {k.lower(): v for k, v in (headers or {}).items()}
    if token is not None:
        hdrs["x-api-token"] = token
    event = {
        "httpMethod": method,
        "path": path,
        "headers": hdrs,
        "queryStringParameters": dict(query) if query else None,
        "isBase64Encoded": False,
    }
    if body is not None:
        event["body"] = body if isinstance(body, str) else json.dumps(body)
    return event


def body_of(response):
    """Decode a handler response's JSON body."""
    return json.loads(response["body"])
