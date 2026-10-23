"""Static frontend hosting (Task 7, design §D.2 / Task 7c §C).

``MahaloFrontendStack`` serves the Next.js static export from a private S3 bucket
via a single-origin CloudFront distribution (OAC, SPA 403/404 -> index.html).

The browser's auth path no longer lives here. The SCP-blocked Cognito
unauthenticated identity pool (and its SigV4 credential-vending role) are removed
in Task 7c: the thin-API Function URL is now ``AuthType=NONE``, so the browser
calls it directly with no AWS credentials and asserts the active persona via the
``X-Mahalo-Persona`` header. This stack therefore has no cross-stack reference to
the API and takes no ``api_stack`` parameter.

CloudFront has a SINGLE S3 origin — it does NOT front the API.

Offline-safety (§E.2): the ``BucketDeployment`` that uploads the built ``out/``
bundle is flag-gated behind ``-c buildFrontend=1`` / ``MAHALO_BUILD_FRONTEND=1``;
the default/offline branch skips it so ``cdk synth`` needs no prior ``next build``.
The bucket + distribution live in THIS stack (not a new stack), so the
``cdk synth --all`` template count stays 11.
"""

from __future__ import annotations

import os

from aws_cdk import (
    CfnOutput,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from constructs import Construct

# Repo root relative to this file (…/infra-cdk/mahalo_infra/frontend_stack.py).
_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_FRONTEND_OUT = os.path.join(_REPO_ROOT, "frontend", "out")


class MahaloFrontendStack(Stack):
    """Private S3 + CloudFront single-origin static hosting."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- (1) Private S3 bucket (OAC-only; no public access). ---
        bucket = s3.Bucket(
            self,
            "FrontendBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            enforce_ssl=True,
        )

        # --- (2) CloudFront: SINGLE S3 origin via OAC, SPA error routing. ---
        distribution = cloudfront.Distribution(
            self,
            "FrontendDistribution",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            ),
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                ),
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                ),
            ],
        )

        # --- (3) Flag-gated bundle upload (offline synth skips it). ---
        build_frontend = bool(self.node.try_get_context("buildFrontend")) or (
            os.environ.get("MAHALO_BUILD_FRONTEND") == "1"
        )
        if build_frontend:
            s3deploy.BucketDeployment(
                self,
                "FrontendDeployment",
                sources=[s3deploy.Source.asset(_FRONTEND_OUT)],
                destination_bucket=bucket,
                distribution=distribution,
                distribution_paths=["/*"],
            )

        self.bucket = bucket
        self.distribution = distribution

        CfnOutput(
            self,
            "FrontendUrl",
            value=f"https://{distribution.distribution_domain_name}",
            description="CloudFront domain serving the static frontend.",
        )
