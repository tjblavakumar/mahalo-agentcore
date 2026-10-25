#!/usr/bin/env python3
"""Idempotent Gitea seeding for the MAHALO real-mode demo.

Runs ON the Gitea EC2 host against http://localhost:3000/api/v1 using the adapter
token from env GITEA_TOKEN. Stdlib only (urllib/json/base64) — no requests/jq.

Seeds, all under owner `mahalo_admin` (single-user + simple-attribution model):
  * 5 repos (payment-service, cart-service, auth-service, product-service,
    order-service), auto_init, default_branch=main.
  * feature branches off main (incl. PAY-107 which has a branch but no PR).
  * 1 representative real-content file + commit per feature branch, commit message
    carrying the persona author name + role + linked story.
  * 1 open PR per feature branch that has a seed PR (PAY-107 has none), with the
    persona label appended to title/body.

Idempotent: every create is preceded by an existence check and skipped if present.
Git commit author stays mahalo_admin; persona attribution lives in text only.
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.request

BASE = "http://localhost:3000/api/v1"
OWNER = "mahalo_admin"
TOKEN = os.environ.get("GITEA_TOKEN", "")

if not TOKEN:
    print("ERROR: GITEA_TOKEN env not set", file=sys.stderr)
    sys.exit(2)


def _req(method, path, body=None, ok=(200, 201), allow_404=False):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "token " + TOKEN)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            code = resp.getcode()
            parsed = json.loads(raw) if raw else None
            return code, parsed
    except urllib.error.HTTPError as e:
        raw = e.read()
        if e.code == 404 and allow_404:
            return 404, None
        try:
            parsed = json.loads(raw) if raw else None
        except Exception:
            parsed = {"message": raw.decode("utf-8", "replace")}
        return e.code, parsed


def ensure_repo(name, description):
    code, _ = _req("GET", "/repos/%s/%s" % (OWNER, name), allow_404=True)
    if code == 200:
        print("  repo exists: %s" % name)
        return
    body = {
        "name": name,
        "description": description,
        "private": False,
        "auto_init": True,
        "default_branch": "main",
    }
    code, resp = _req("POST", "/user/repos", body=body, ok=(201,))
    if code != 201:
        raise RuntimeError("repo create failed %s: %s %s" % (name, code, resp))
    print("  repo created: %s" % name)


def ensure_branch(repo, branch):
    code, _ = _req(
        "GET", "/repos/%s/%s/branches/%s" % (OWNER, repo, branch), allow_404=True
    )
    if code == 200:
        print("    branch exists: %s" % branch)
        return
    body = {"new_branch_name": branch, "old_branch_name": "main"}
    code, resp = _req(
        "POST", "/repos/%s/%s/branches" % (OWNER, repo), body=body, ok=(201,)
    )
    if code != 201:
        raise RuntimeError("branch create failed %s/%s: %s %s" % (repo, branch, code, resp))
    print("    branch created: %s" % branch)


def ensure_file(repo, branch, path, content, message):
    api = "/repos/%s/%s/contents/%s" % (OWNER, repo, path)
    code, existing = _req("GET", api + "?ref=" + branch, allow_404=True)
    content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
    body = {"content": content_b64, "message": message, "branch": branch}
    if code == 200 and isinstance(existing, dict) and existing.get("sha"):
        print("    file exists (skip commit): %s" % path)
        return
    code, resp = _req("POST", api, body=body, ok=(200, 201))
    if code not in (200, 201):
        raise RuntimeError("file commit failed %s/%s %s: %s %s" % (repo, branch, path, code, resp))
    print("    file committed: %s on %s" % (path, branch))


def ensure_pr(repo, head, base, title, body):
    code, prs = _req(
        "GET",
        "/repos/%s/%s/pulls?state=all&limit=50" % (OWNER, repo),
        allow_404=True,
    )
    if code == 200 and isinstance(prs, list):
        for p in prs:
            h = (p.get("head") or {}).get("ref")
            if h == head:
                print("    PR exists for head %s (#%s)" % (head, p.get("number")))
                return
    reqbody = {"head": head, "base": base, "title": title, "body": body}
    code, resp = _req(
        "POST", "/repos/%s/%s/pulls" % (OWNER, repo), body=reqbody, ok=(201,)
    )
    if code != 201:
        raise RuntimeError("PR create failed %s head=%s: %s %s" % (repo, head, code, resp))
    print("    PR created: #%s %s" % (resp.get("number"), title))


# ---- Seed matrix (from github/seed_data.py + jira roles) --------------------
# Each entry: repo -> {description, branches:[{branch, file, content, commit_msg,
#   pr_title, pr_body or None}]}

SEED = [
    {
        "name": "payment-service",
        "description": "Payment processing microservice (Stripe, Apple Pay, Google Pay)",
        "branches": [
            {
                "branch": "feature/PAY-105-google-pay",
                "file": "src/payments/google_pay.py",
                "content": '"""Google Pay via Payment Request API (PAY-105)."""\n\ndef render_google_pay_button():\n    return "google-pay-button"\n',
                "commit_msg": "feat: add Google Pay button component — authored by Marcus Chen (Product Manager)  [PAY-105]",
                "pr_title": "feat: Google Pay integration — authored by Marcus Chen (Product Manager)",
                "pr_body": "Implements Google Pay using Payment Request API. Linked to PAY-105.\n\nauthored by Marcus Chen (Product Manager)\nLinked story: PAY-105",
            },
            {
                "branch": "feature/PAY-106-payment-retry",
                "file": "src/payments/retry.py",
                "content": '"""Payment retry with exponential backoff (PAY-106)."""\n\nBACKOFF = [1, 4, 16]\n',
                "commit_msg": "feat: add retry mechanism with exponential backoff — authored by Raj Patel (Developer)  [PAY-106]",
                "pr_title": "feat: Payment retry with exponential backoff — authored by Raj Patel (Developer)",
                "pr_body": "Adds automatic retry mechanism for failed payments. Max 3 attempts. Linked to PAY-106.\n\nauthored by Raj Patel (Developer)\nLinked story: PAY-106",
            },
            {
                "branch": "feature/PAY-107-multi-currency",
                "file": "src/payments/multi_currency.py",
                "content": '"""Multi-currency support EUR/GBP/JPY (PAY-107)."""\n\nCURRENCIES = ["USD", "EUR", "GBP", "JPY"]\n',
                "commit_msg": "feat: multi-currency scaffolding — authored by Marcus Chen (Product Manager)  [PAY-107]",
                "pr_title": None,
                "pr_body": None,
            },
            {
                "branch": "feature/PAY-108-analytics-dashboard",
                "file": "src/payments/analytics.py",
                "content": '"""Payment analytics endpoints (PAY-108)."""\n\ndef success_rate():\n    return 0.0\n',
                "commit_msg": "feat: payment success rate API endpoint — authored by David Kim (Executive)  [PAY-108]",
                "pr_title": "feat: Payment analytics dashboard backend — authored by David Kim (Executive)",
                "pr_body": "API endpoints for payment analytics: success rates, failure reasons, revenue metrics. Linked to PAY-108.\n\nauthored by David Kim (Executive)\nLinked story: PAY-108",
            },
        ],
    },
    {
        "name": "cart-service",
        "description": "Shopping cart management and checkout flow",
        "branches": [
            {
                "branch": "feature/CART-204-wishlist-to-cart",
                "file": "src/cart/wishlist.py",
                "content": '"""Move wishlist items to cart (CART-204)."""\n\ndef move_to_cart(item_id):\n    return {"moved": item_id}\n',
                "commit_msg": "feat: add move-to-cart button on wishlist items — authored by Sarah Johnson (Developer)  [CART-204]",
                "pr_title": "feat: Wishlist to cart conversion — authored by Sarah Johnson (Developer)",
                "pr_body": "Move items from wishlist to cart with stock check. Linked to CART-204.\n\nauthored by Sarah Johnson (Developer)\nLinked story: CART-204",
            },
            {
                "branch": "feature/CART-206-shipping-estimator",
                "file": "src/cart/shipping_estimator.py",
                "content": '"""ZIP-based shipping cost estimator (CART-206)."""\n\ndef estimate(zip_code):\n    return {"zip": zip_code, "cost": 0.0}\n',
                "commit_msg": "feat: ZIP code based shipping estimation — authored by Sarah Johnson (Developer)  [CART-206]",
                "pr_title": "feat: Shipping cost estimator — authored by Sarah Johnson (Developer)",
                "pr_body": "ZIP-based shipping cost estimation in cart. Linked to CART-206.\n\nauthored by Sarah Johnson (Developer)\nLinked story: CART-206",
            },
        ],
    },
    {
        "name": "auth-service",
        "description": "User authentication, authorization, and SSO",
        "branches": [
            {
                "branch": "feature/AUTH-304-totp-2fa",
                "file": "src/auth/totp.py",
                "content": '"""TOTP 2FA setup + verification (AUTH-304)."""\n\ndef generate_secret():\n    return "BASE32SECRET"\n',
                "commit_msg": "feat: TOTP secret generation and QR code — authored by Raj Patel (Developer)  [AUTH-304]",
                "pr_title": "feat: TOTP two-factor authentication — authored by Raj Patel (Developer)",
                "pr_body": "QR code setup, TOTP verification, backup codes. Linked to AUTH-304.\n\nauthored by Raj Patel (Developer)\nLinked story: AUTH-304",
            },
            {
                "branch": "feature/AUTH-306-saml-sso",
                "file": "src/auth/saml_sso.py",
                "content": '"""SAML 2.0 SSO for enterprise (AUTH-306)."""\n\ndef sp_metadata():\n    return "<EntityDescriptor/>"\n',
                "commit_msg": "feat: SAML service provider metadata endpoint — authored by Lava Dev (Developer)  [AUTH-306]",
                "pr_title": "feat: SAML 2.0 SSO for enterprise customers — authored by Lava Dev (Developer)",
                "pr_body": "Adds SAML-based single sign-on with IdP- and SP-initiated flows and JIT provisioning. Linked to AUTH-306.\n\nauthored by Lava Dev (Developer)\nLinked story: AUTH-306",
            },
        ],
    },
    {
        "name": "product-service",
        "description": "Product catalog, search, and inventory management",
        "branches": [
            {
                "branch": "feature/PROD-403-recommendations",
                "file": "src/product/recommendations.py",
                "content": '"""Collaborative-filtering recommendations (PROD-403)."""\n\ndef recommend(user_id):\n    return []\n',
                "commit_msg": "feat: collaborative filtering model training pipeline — authored by Emily Zhang (Developer)  [PROD-403]",
                "pr_title": "feat: Product recommendations engine — authored by Emily Zhang (Developer)",
                "pr_body": "Collaborative filtering based recommendations. Linked to PROD-403.\n\nauthored by Emily Zhang (Developer)\nLinked story: PROD-403",
            },
        ],
    },
    {
        "name": "order-service",
        "description": "Order processing, fulfillment, and tracking",
        "branches": [
            {
                "branch": "feature/ORD-503-split-fulfillment",
                "file": "src/order/split_fulfillment.py",
                "content": '"""Multi-warehouse split fulfillment (ORD-503)."""\n\ndef route(order):\n    return {"shipments": []}\n',
                "commit_msg": "feat: warehouse proximity routing algorithm — authored by David Kim (Executive)  [ORD-503]",
                "pr_title": "feat: Split order fulfillment — authored by David Kim (Executive)",
                "pr_body": "Multi-warehouse shipping with routing algorithm. Linked to ORD-503.\n\nauthored by David Kim (Executive)\nLinked story: ORD-503",
            },
        ],
    },
]


def main():
    repo_count = 0
    branch_count = 0
    pr_count = 0
    for repo in SEED:
        print("repo: %s" % repo["name"])
        ensure_repo(repo["name"], repo["description"])
        repo_count += 1
        for b in repo["branches"]:
            ensure_branch(repo["name"], b["branch"])
            branch_count += 1
            ensure_file(
                repo["name"], b["branch"], b["file"], b["content"], b["commit_msg"]
            )
            if b["pr_title"]:
                ensure_pr(
                    repo["name"], b["branch"], "main", b["pr_title"], b["pr_body"]
                )
                pr_count += 1
    print("SEED SUMMARY: repos=%d branches=%d prs_attempted=%d" % (repo_count, branch_count, pr_count))


if __name__ == "__main__":
    main()
