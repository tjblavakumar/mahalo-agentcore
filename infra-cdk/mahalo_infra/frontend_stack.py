"""Static frontend hosting + browser auth (Task 7, design §D.2/§B.2).

``MahaloFrontendStack`` serves the Next.js static export from a private S3 bucket
via a single-origin CloudFront distribution (OAC, SPA 403/404 -> index.html). It
provisions the browser's auth path too: an UNAUTHENTICATED Cognito identity pool
whose unauthenticated role is granted exactly ``lambda:InvokeFunctionUrl`` on the
thin-API function ARN, so the browser fetches short-lived creds and signs SigV4
calls directly to the Function URL (CORS handled on the API side, §B.4).

CloudFront has a SINGLE S3 origin — it does NOT front the API (signing for the
CloudFront host would 403 on the Host rewrite, §B.4). ``api_stack`` is taken ONLY
to read ``api_stack.function.function_arn`` for the role policy; no Function-URL
string is read (none is exposed) and the API's CORS is NOT mutated here (that is
a ``MahaloApiStack`` re-deploy, §D.2 step 5).

Offline-safety (§E.2): the ``BucketDeployment`` that uploads the built ``out/``
bundle is flag-gated behind ``-c buildFrontend=1`` / ``MAHALO_BUILD_FRONTEND=1``;
the default/offline branch skips it so ``cdk synth`` needs no prior ``next build``.
The bucket + distribution + identity pool/role live in THIS stack (not a new
stack), so the ``cdk synth --all`` template count is 11.
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
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from constructs import Construct

# Repo root relative to this file (…/infra-cdk/mahalo_infra/frontend_stack.py).
_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_FRONTEND_OUT = os.path.join(_REPO_ROOT, "frontend", "out")


class MahaloFrontendStack(Stack):
    """Private S3 + CloudFront single-origin + Cognito unauthenticated pool."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        api_stack: "Stack",
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

        # --- (4) Cognito unauthenticated identity pool + role (§B.2). ---
        identity_pool = cognito.CfnIdentityPool(
            self,
            "IdentityPool",
            allow_unauthenticated_identities=True,
        )
        unauth_role = iam.Role(
            self,
            "UnauthRole",
            assumed_by=iam.FederatedPrincipal(
                "cognito-identity.amazonaws.com",
                conditions={
                    "StringEquals": {
                        "cognito-identity.amazonaws.com:aud": identity_pool.ref
                    },
                    "ForAnyValue:StringLike": {
                        "cognito-identity.amazonaws.com:amr": "unauthenticated"
                    },
                },
                assume_role_action="sts:AssumeRoleWithWebIdentity",
            ),
        )
        # Least privilege: only InvokeFunctionUrl on the thin-API function ARN.
        unauth_role.add_to_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunctionUrl"],
                resources=[api_stack.function.function_arn],
            )
        )
        cognito.CfnIdentityPoolRoleAttachment(
            self,
            "IdentityPoolRoleAttachment",
            identity_pool_id=identity_pool.ref,
            roles={"unauthenticated": unauth_role.role_arn},
        )

        self.bucket = bucket
        self.distribution = distribution
        self.identity_pool = identity_pool

        CfnOutput(
            self,
            "IdentityPoolId",
            value=identity_pool.ref,
            description="Cognito identity pool id -> NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID.",
        )
        CfnOutput(
            self,
            "FrontendUrl",
            value=f"https://{distribution.distribution_domain_name}",
            description="CloudFront domain serving the static frontend.",
        )
