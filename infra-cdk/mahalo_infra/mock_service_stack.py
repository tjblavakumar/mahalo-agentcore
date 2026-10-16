"""Reusable CDK stack for one mock service Lambda.

Each instance provisions, for a single service (jira/confluence/github/
servicenow):

1. A DynamoDB table ``mahalo-mock-<svc>`` (pk/sk string keys, PAY_PER_REQUEST,
   RemovalPolicy.DESTROY for clean monthly-reset teardown).
2. A ``python3.13`` Lambda bundling ``../tools-lambdas`` (the ``common/`` package
   plus this one service directory; the other three services, tests, venv, caches
   and dev requirements are excluded from the asset) whose handler is
   ``<svc>.handler.lambda_handler``.
3. Least-privilege IAM: the table grants read+write to this function only.
4. A Function URL with ``AuthType=NONE`` (the Lambdas enforce a static
   ``X-API-Token`` themselves).

Both the Function URL and the function ARN are emitted as CfnOutputs so Task 4's
Gateway stack can import them without this stack changing.
"""

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_lambda as lambda_
from constructs import Construct

# Asset root, relative to infra-cdk/ (the dir cdk runs ``python app.py`` from).
_ASSET_PATH = "../tools-lambdas"

# All four service package dirs; each function excludes the three it does not own.
_ALL_SERVICES = ("jira", "confluence", "github", "servicenow")

# Default MOCK_<SVC>_TOKEN values, matching agent/config.py so the agent can reach
# the deployed Lambdas by only overriding the four *_URL env vars.
_DEFAULT_TOKENS = {
    "jira": "mock-jira-token-12345",
    "confluence": "mock-confluence-token-12345",
    "github": "mock-github-token-12345",
    "servicenow": "mock-servicenow-token-12345",
}

# CfnOutput logical-id stems per service (Task-4 Gateway import contract).
_OUTPUT_IDS = {
    "jira": ("JiraUrl", "JiraArn"),
    "confluence": ("ConfluenceUrl", "ConfluenceArn"),
    "github": ("GithubUrl", "GithubArn"),
    "servicenow": ("ServiceNowUrl", "ServiceNowArn"),
}


class MockServiceStack(Stack):
    """One DynamoDB table + Lambda + Function URL for a single mock service."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        service: str,
        default_token: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        if service not in _ALL_SERVICES:
            raise ValueError(f"Unknown service: {service!r}")

        table_name = f"mahalo-mock-{service}"
        token = default_token or _DEFAULT_TOKENS[service]
        token_env_key = f"MOCK_{service.upper()}_TOKEN"

        # (1) DynamoDB table: pk (HASH) + sk (RANGE), on-demand billing.
        table = dynamodb.Table(
            self,
            "Table",
            table_name=table_name,
            partition_key=dynamodb.Attribute(
                name="pk", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="sk", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # (2) Lambda: bundle common/ + only this service dir.
        other_services = [s for s in _ALL_SERVICES if s != service]
        exclude = [
            *other_services,
            "tests",
            ".venv",
            "**/__pycache__",
            "requirements-dev.txt",
            ".gitkeep",
        ]
        fn = lambda_.Function(
            self,
            "Function",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler=f"{service}.handler.lambda_handler",
            code=lambda_.Code.from_asset(_ASSET_PATH, exclude=exclude),
            memory_size=256,
            timeout=Duration.seconds(30),
            environment={
                "TABLE_NAME": table_name,
                token_env_key: token,
            },
        )

        # (3) Least-privilege IAM: this table only.
        table.grant_read_write_data(fn)

        # (4) Function URL, no IAM auth (the Lambda enforces X-API-Token itself).
        fn_url = fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
        )

        # CfnOutputs for Task 4 Gateway import.
        url_id, arn_id = _OUTPUT_IDS[service]
        CfnOutput(
            self,
            url_id,
            value=fn_url.url,
            description=f"{service} mock Lambda Function URL",
        )
        CfnOutput(
            self,
            arn_id,
            value=fn.function_arn,
            description=f"{service} mock Lambda function ARN",
        )

        self.table = table
        self.function = fn
        self.function_url = fn_url
