"""Regression test for the Runtime image-asset nesting bug (offline, no Docker).

Root cause: the ``-c buildImage=1`` deploy branch built the Runtime image asset
from ``_REPO_ROOT`` (the whole repo) with NO ``exclude`` and NO ``.dockerignore``.
The context root contains ``infra-cdk/cdk.out`` — the CDK output dir that itself
holds staged assets — so CDK copied ``cdk.out`` into the new asset, nesting it
recursively (``cdk.out/asset.<hash>/infra-cdk/cdk.out/asset.<hash>/…``) until
staging failed with ``ENAMETOOLONG``. The committed dev venvs (``agent/.venv``,
``api/.venv``) made the asset huge and are what triggered it.

This never surfaced in offline ``cdk synth`` (the default branch uses
``from_image_uri`` — no asset staging) and the real staging needs Docker (absent
on this VDI), so the guard is asserted structurally: the exclude constant used by
``from_asset(exclude=…)`` and the repo-root ``.dockerignore`` must both carry the
critical entries. Against the pre-fix code BOTH assertions fail — the constant did
not exist (ImportError) and the ``.dockerignore`` did not exist.
"""

import os

import pytest

from mahalo_infra.api_stack import _API_ASSET_EXCLUDE
from mahalo_infra.runtime_stack import _IMAGE_ASSET_EXCLUDE, _REPO_ROOT

# The exclusions that, if missing, reintroduce the recursion / bloat.
_CRITICAL = ("cdk.out", ".venv", "__pycache__", ".git", "node_modules")


def _covers(patterns, token):
    """A token is covered if any pattern is exactly it or a ``**/<token>`` glob."""
    return any(p == token or p == f"**/{token}" for p in patterns)


def test_runtime_exclude_covers_recursion_and_bloat_sources():
    # cdk.out (the recursion source) and .venv (the bloat) MUST be excluded, plus
    # the rest of the critical set. Pre-fix this import fails (constant absent).
    for token in _CRITICAL:
        assert _covers(_IMAGE_ASSET_EXCLUDE, token), (
            f"Runtime image asset exclude is missing {token!r}; without it the "
            f"asset re-nests/bloats: {_IMAGE_ASSET_EXCLUDE}"
        )
    # The explicit repo-root cdk.out path is pinned (not just the glob) because it
    # is the exact recursion source confirmed in the live deploy log.
    assert "infra-cdk/cdk.out" in _IMAGE_ASSET_EXCLUDE


def test_runtime_exclude_keeps_agent_package():
    # The image needs the agent/ package + its requirements.txt — never exclude them.
    for bad in _IMAGE_ASSET_EXCLUDE:
        assert "agent/requirements.txt" not in bad
        assert bad not in ("agent", "agent/", "agent/**")


def test_api_exclude_covers_venv_and_cdk_out():
    for token in ("cdk.out", ".venv", "__pycache__"):
        assert _covers(_API_ASSET_EXCLUDE, token), (
            f"API Lambda asset exclude is missing {token!r}: {_API_ASSET_EXCLUDE}"
        )


def test_dockerignore_exists_at_build_context_root():
    # The Docker daemon honors .dockerignore relative to the build-context root,
    # which is the first arg to from_asset — _REPO_ROOT for the Runtime image.
    dockerignore = os.path.join(_REPO_ROOT, ".dockerignore")
    assert os.path.isfile(dockerignore), (
        f".dockerignore missing at the build-context root ({_REPO_ROOT}); the "
        "Docker daemon then tars cdk.out/.venv into the image context."
    )
    with open(dockerignore, "r", encoding="utf-8") as fh:
        body = fh.read()
    for token in _CRITICAL:
        assert token in body, f".dockerignore is missing a {token!r} rule"


def test_dockerignore_does_not_exclude_agent_package():
    # A rule that drops the agent package/requirements would break the image build.
    dockerignore = os.path.join(_REPO_ROOT, ".dockerignore")
    with open(dockerignore, "r", encoding="utf-8") as fh:
        rules = [
            line.strip()
            for line in fh
            if line.strip() and not line.lstrip().startswith("#")
        ]
    for rule in rules:
        assert rule not in ("agent", "agent/", "agent/**", "agent/requirements.txt")
