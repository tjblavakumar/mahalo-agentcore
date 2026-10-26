"""Thin-API Function-URL Lambda (Task 6, design §E.2 / Task 7c §B).

``MahaloApiStack`` provisions the stateless FastAPI forwarder in ``api/`` as a
``python3.13`` Lambda behind a Function URL with ``AuthType=NONE`` (demo posture,
Task 7c §B): the SCP-blocked Cognito identity pool is removed, so the browser
calls this URL directly with no AWS credentials and asserts the active persona
via the ``X-Mahalo-Persona`` header (mapped to ``{developer_id, role}`` in
``api/app/auth.py``). The Lambda role is granted
``bedrock-agentcore:InvokeAgentRuntime`` on the Runtime ARN, and
``MAHALO_RUNTIME_ARN`` is wired in from the Runtime stack.

Security tradeoff (explicitly ACCEPTED): ``AuthType=NONE`` makes this Function
URL callable by anyone who knows the URL. For a single-user demo over mock data
with no live systems this is accepted; GovCloud/OKTA replaces it later. The URL
is not published in source — it is supplied to the frontend at deploy time.

Offline-safety (§E.4): dependency bundling runs Docker, which the offline gate
forbids, so bundling is flag-gated exactly like the image build. On the default
branch the Lambda is packaged as a plain asset (``Code.from_asset("../api")``) so
``cdk synth`` never invokes Docker; on the operator-deploy branch
(``-c buildImage=1`` / ``MAHALO_BUILD_IMAGE=1``) ``BundlingOptions`` installs
``requirements.txt`` into the asset so ``fastapi``/``mangum``/``boto3`` ship.
"""

from __future__ import annotations

import os

from aws_cdk import BundlingOptions, CfnOutput, Duration, Stack
from aws_cdk import aws_lambda as lambda_
from constructs import Construct

# …/infra-cdk/mahalo_infra/api_stack.py -> repo root -> api/.
_API_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "api",
)

# Keep the local dev virtualenv + caches out of the Lambda asset. api/.venv (~60MB)
# is a committed dev venv — the operator-deploy branch installs deps from
# requirements.txt via BundlingOptions, so the venv is never needed in the asset and
# only bloats staging. api/ has no cdk.out, but the glob guards against it regardless.
_API_ASSET_EXCLUDE = [
    "**/cdk.out",
    ".venv",
    "**/.venv",
    "**/__pycache__",
    "**/*.pyc",
    ".pytest_cache",
    "**/.pytest_cache",
]


class MahaloApiStack(Stack):
    """Function-URL Lambda forwarding to the AgentCore Runtime."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        runtime_stack: "Stack",
        dashboard_stack: "Stack",
        identity_enabled: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        runtime = runtime_stack.runtime
        dashboard_table = dashboard_stack.table

        build_image = bool(self.node.try_get_context("buildImage")) or (
            os.environ.get("MAHALO_BUILD_IMAGE") == "1"
        )
        if build_image:
            # Operator deploy: bundle deps into the asset via Docker.
            code = lambda_.Code.from_asset(
                _API_DIR,
                exclude=_API_ASSET_EXCLUDE,
                bundling=BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_13.bundling_image,
                    # The Lambda function below runs on ARM64, so native wheels
                    # (pydantic_core etc.) MUST be aarch64/manylinux2014. Pin the
                    # pip platform explicitly so the result does not depend on the
                    # build host's architecture (the EC2 builder is Graviton/ARM64,
                    # but pinning keeps this correct on any builder).
                    command=[
                        "bash",
                        "-c",
                        "pip install -r requirements.txt "
                        "--platform manylinux2014_aarch64 --python-version 3.13 "
                        "--only-binary=:all: --implementation cp "
                        "-t /asset-output && cp -r app /asset-output",
                    ],
                ),
            )
        else:
            # Offline gate: plain asset, no Docker. (A pre-built deps layer is the
            # offline-branch fallback for a runnable Lambda; for the synth gate the
            # plain asset is sufficient and Docker-free.)
            code = lambda_.Code.from_asset(_API_DIR, exclude=_API_ASSET_EXCLUDE)

        fn = lambda_.Function(
            self,
            "ApiFn",
            runtime=lambda_.Runtime.PYTHON_3_13,
            # ARM64 to match the aarch64 wheels bundled above (and the Graviton
            # builder). Mismatch -> ImportError: pydantic_core._pydantic_core.
            architecture=lambda_.Architecture.ARM_64,
            handler="app.main.handler",
            code=code,
            timeout=Duration.seconds(300),
            memory_size=512,
            environment={
                # AWS_REGION is provided automatically by the Lambda runtime and
                # is read by api/app/config.py; it must not be set here (reserved).
                "MAHALO_RUNTIME_ARN": runtime.agent_runtime_arn,
                "MAHALO_IDENTITY_ENABLED": "true" if identity_enabled else "false",
                "MAHALO_DASHBOARD_TABLE": dashboard_table.table_name,
            },
        )

        # Thin API -> Runtime: SigV4-signed InvokeAgentRuntime on the Runtime ARN.
        runtime.grant_invoke_runtime(fn)
        # Thin API -> dashboards table: GetItem/PutItem on the one persona item.
        dashboard_table.grant_read_write_data(fn)
        if identity_enabled:
            # Per-user invoke requires the additional IAM action (§B.5 / §D.4).
            runtime.grant_invoke_runtime_for_user(fn)

        # Browser (CloudFront static app) calls this Function URL DIRECTLY with
        # no AWS credentials (AuthType=NONE, Task 7c §B); cross-origin is handled
        # by the CORS block here. Because no request is signed, a wildcard origin
        # is safe to CORS (there are no credentials to gate) and removes the
        # chicken-and-egg re-deploy dance of pinning the CloudFront domain before
        # the frontend stack exists; CORS is not an auth control here. The custom
        # X-Mahalo-Persona header MUST be allowed or the browser preflight fails.
        url = fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
            cors=lambda_.FunctionUrlCorsOptions(
                allowed_origins=["*"],
                # POST (/chat, /chat/approve) + GET (/healthz). The OPTIONS
                # preflight is answered automatically by the Function URL CORS
                # layer and is NOT a valid allowed-method value (CloudFormation
                # rejects "OPTIONS"), so it is intentionally omitted here while
                # still being served.
                allowed_methods=[
                    lambda_.HttpMethod.POST,
                    lambda_.HttpMethod.GET,
                    # PUT /dashboard/widgets (custom dashboard overwrite-save).
                    lambda_.HttpMethod.PUT,
                ],
                # No SigV4 headers — nothing is signed anymore. Only the content
                # type and the persona header the browser sends.
                allowed_headers=[
                    "Content-Type",
                    "X-Mahalo-Persona",
                ],
                max_age=Duration.seconds(300),
            ),
        )

        CfnOutput(self, "RuntimeApiUrl", value=url.url)

        self.function = fn
