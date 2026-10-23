"""Thin-API Function-URL Lambda (Task 6, design §E.2).

``MahaloApiStack`` provisions the stateless FastAPI forwarder in ``api/`` as a
``python3.13`` Lambda behind a Function URL with ``AuthType=AWS_IAM``. The Lambda
role is granted ``bedrock-agentcore:InvokeAgentRuntime`` on the Runtime ARN, and
``MAHALO_RUNTIME_ARN`` is wired in from the Runtime stack.

Offline-safety (§E.4): dependency bundling runs Docker, which the offline gate
forbids, so bundling is flag-gated exactly like the image build. On the default
branch the Lambda is packaged as a plain asset (``Code.from_asset("../api")``) so
``cdk synth`` never invokes Docker; on the operator-deploy branch
(``-c buildImage=1`` / ``MAHALO_BUILD_IMAGE=1``) ``BundlingOptions`` installs
``requirements.txt`` into the asset so ``fastapi``/``mangum``/``boto3`` ship.
"""

from __future__ import annotations

import os

from aws_cdk import BundlingOptions, CfnOutput, CfnParameter, Duration, Stack
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
        identity_enabled: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        runtime = runtime_stack.runtime

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
            },
        )

        # Thin API -> Runtime: SigV4-signed InvokeAgentRuntime on the Runtime ARN.
        runtime.grant_invoke_runtime(fn)
        if identity_enabled:
            # Per-user invoke requires the additional IAM action (§B.5 / §D.4).
            runtime.grant_invoke_runtime_for_user(fn)

        # Browser (CloudFront static app) calls this Function URL DIRECTLY and
        # signs SigV4 for its own host (design §B.4); cross-origin is handled by
        # a CORS block here. The auth type stays AWS_IAM (no downgrade). The
        # allowed origin is the CloudFront frontend domain — a CfnParameter (NOT
        # '*', because signed requests carry credentials); the operator sets it
        # when re-deploying this stack after the frontend stack is up (§D.2 step 5).
        frontend_origin = CfnParameter(
            self,
            "FrontendOrigin",
            type="String",
            default="https://example.cloudfront.net",
            description=(
                "CloudFront frontend origin allowed by the Function URL CORS "
                "policy (e.g. https://<dist>.cloudfront.net). Set on re-deploy "
                "once the frontend stack's domain is known (design §D.2 step 5)."
            ),
        ).value_as_string

        url = fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.AWS_IAM,
            cors=lambda_.FunctionUrlCorsOptions(
                allowed_origins=[frontend_origin],
                # POST (/chat, /chat/approve) + GET (/healthz). The OPTIONS
                # preflight is answered automatically by the Function URL CORS
                # layer and is NOT a valid allowed-method value (CloudFormation
                # rejects "OPTIONS"), so it is intentionally omitted here while
                # still being served unsigned — the §B.4 intent holds.
                allowed_methods=[
                    lambda_.HttpMethod.POST,
                    lambda_.HttpMethod.GET,
                ],
                allowed_headers=[
                    "Authorization",
                    "X-Amz-Date",
                    "X-Amz-Security-Token",
                    "X-Amz-Content-Sha256",
                    "Content-Type",
                ],
                max_age=Duration.seconds(300),
            ),
        )

        CfnOutput(self, "RuntimeApiUrl", value=url.url)

        self.function = fn
