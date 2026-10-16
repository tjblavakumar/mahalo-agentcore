"""Seed data for the Mock ServiceNow service.

Aligned to the existing services (repos/projects) and developers (dev-1..dev-6)
used by the JIRA/GitHub/Confluence mocks, so deployments and incidents can be
correlated across systems.

Service IDs mirror the GitHub repos / JIRA projects:
  payment-service (repo-1 / PAY), cart-service (repo-2 / CART),
  auth-service (repo-3 / AUTH), product-service (repo-4 / PROD),
  order-service (repo-5 / ORD).
"""

SERVICES = [
    {"id": "payment-service", "repo_id": "repo-1", "project_id": "PAY", "name": "Payment Service"},
    {"id": "cart-service", "repo_id": "repo-2", "project_id": "CART", "name": "Cart Service"},
    {"id": "auth-service", "repo_id": "repo-3", "project_id": "AUTH", "name": "Auth Service"},
    {"id": "product-service", "repo_id": "repo-4", "project_id": "PROD", "name": "Product Service"},
    {"id": "order-service", "repo_id": "repo-5", "project_id": "ORD", "name": "Order Service"},
]

# environment: staging | production
# status: success | failed | rolled_back | in_progress
DEPLOYMENTS = [
    {
        "id": "DEP-1001",
        "service": "auth-service",
        "environment": "production",
        "version": "v2.4.0",
        "status": "success",
        "deployed_by": "dev-3",
        "deployed_at": "2026-08-21T14:30:00Z",
        "duration_seconds": 214,
        "linked_story": "AUTH-304",
        "linked_pr": 56,
        "notes": "TOTP 2FA rollout to production.",
    },
    {
        "id": "DEP-1002",
        "service": "payment-service",
        "environment": "production",
        "version": "v3.1.2",
        "status": "success",
        "deployed_by": "dev-1",
        "deployed_at": "2026-08-20T09:10:00Z",
        "duration_seconds": 178,
        "linked_story": "PAY-105",
        "linked_pr": 142,
        "notes": "Google Pay integration.",
    },
    {
        "id": "DEP-1003",
        "service": "product-service",
        "environment": "production",
        "version": "v1.9.0",
        "status": "failed",
        "deployed_by": "dev-4",
        "deployed_at": "2026-08-18T16:45:00Z",
        "duration_seconds": 92,
        "linked_story": "PROD-403",
        "linked_pr": 93,
        "notes": "Recommendations engine deploy failed on migration step.",
    },
    {
        "id": "DEP-1004",
        "service": "product-service",
        "environment": "production",
        "version": "v1.9.1",
        "status": "rolled_back",
        "deployed_by": "dev-4",
        "deployed_at": "2026-08-18T18:05:00Z",
        "duration_seconds": 140,
        "linked_story": "PROD-403",
        "linked_pr": 93,
        "notes": "Rolled back after elevated error rate post-deploy.",
    },
    {
        "id": "DEP-1005",
        "service": "order-service",
        "environment": "staging",
        "version": "v2.0.0-rc1",
        "status": "success",
        "deployed_by": "dev-5",
        "deployed_at": "2026-08-20T11:20:00Z",
        "duration_seconds": 165,
        "linked_story": "ORD-503",
        "linked_pr": 71,
        "notes": "Split fulfillment release candidate to staging.",
    },
    {
        "id": "DEP-1006",
        "service": "cart-service",
        "environment": "production",
        "version": "v4.2.3",
        "status": "success",
        "deployed_by": "dev-2",
        "deployed_at": "2026-08-19T13:00:00Z",
        "duration_seconds": 121,
        "linked_story": "CART-204",
        "linked_pr": 87,
        "notes": "Wishlist to cart conversion.",
    },
]

# severity: P1 (critical) | P2 (high) | P3 (medium) | P4 (low)
# status: open | investigating | resolved
INCIDENTS = [
    {
        "id": "INC-2001",
        "title": "Product recommendations returning 500s after deploy",
        "severity": "P1",
        "status": "resolved",
        "affected_service": "product-service",
        "assignee": "dev-4",
        "opened_at": "2026-08-18T16:52:00Z",
        "resolved_at": "2026-08-18T18:10:00Z",
        "linked_deployment": "DEP-1003",
        "description": "Failed migration during v1.9.0 caused 500s. Resolved by rollback to v1.8.x.",
    },
    {
        "id": "INC-2002",
        "title": "Elevated payment latency during peak",
        "severity": "P2",
        "status": "investigating",
        "affected_service": "payment-service",
        "assignee": "dev-1",
        "opened_at": "2026-08-21T19:30:00Z",
        "resolved_at": None,
        "linked_deployment": None,
        "description": "p95 latency above SLA during evening peak. Investigating provider timeouts.",
    },
    {
        "id": "INC-2003",
        "title": "2FA SMS fallback intermittently failing",
        "severity": "P3",
        "status": "open",
        "affected_service": "auth-service",
        "assignee": "dev-3",
        "opened_at": "2026-08-22T08:15:00Z",
        "resolved_at": None,
        "linked_deployment": "DEP-1001",
        "description": "Some users report SMS fallback not delivered after TOTP rollout.",
    },
    {
        "id": "INC-2004",
        "title": "Cart totals off by rounding for JPY",
        "severity": "P4",
        "status": "open",
        "affected_service": "cart-service",
        "assignee": "dev-2",
        "opened_at": "2026-08-20T10:40:00Z",
        "resolved_at": None,
        "linked_deployment": None,
        "description": "Minor rounding discrepancy for JPY carts. Low impact.",
    },
]


_SERVICE_CONTEXT = {
    "payment-service": {
        "project": "PAY",
        "component": "payment authorization and refund flows",
        "release_topics": [
            "3DS challenge handling",
            "wallet tokenization",
            "refund reconciliation",
            "payment provider retries",
            "webhook signature validation",
            "settlement reporting",
            "card vault rotation",
            "fraud decision caching",
            "capture idempotency",
        ],
        "incident_topics": [
            "authorization timeouts",
            "duplicate webhook delivery",
            "refund reconciliation lag",
            "3DS challenge failures",
            "wallet token refresh errors",
            "provider response spikes",
            "settlement export delays",
            "card vault connectivity",
            "capture retry exhaustion",
        ],
        "assignee": "dev-1",
    },
    "cart-service": {
        "project": "CART",
        "component": "cart pricing and checkout calculations",
        "release_topics": [
            "promotional pricing rules",
            "cart reservation expiry",
            "tax calculation caching",
            "multi-currency rounding",
            "guest cart merge",
            "checkout item validation",
            "shipping estimate refresh",
            "bundle discount calculation",
            "cart persistence failover",
        ],
        "incident_topics": [
            "stale cart totals",
            "coupon validation errors",
            "guest cart merge failures",
            "tax calculation timeouts",
            "reservation expiry mismatches",
            "shipping estimate drift",
            "bundle discount regressions",
            "checkout validation failures",
            "cart persistence errors",
        ],
        "assignee": "dev-2",
    },
    "auth-service": {
        "project": "AUTH",
        "component": "identity, login, and access management",
        "release_topics": [
            "SSO session renewal",
            "TOTP enrollment",
            "password reset throttling",
            "OAuth callback validation",
            "login risk scoring",
            "device trust registration",
            "SMS fallback routing",
            "service account rotation",
            "session revocation propagation",
        ],
        "incident_topics": [
            "login latency",
            "SSO callback failures",
            "password reset delivery",
            "TOTP enrollment errors",
            "session revocation lag",
            "OAuth token validation",
            "SMS fallback delivery",
            "device trust mismatches",
            "service account authentication",
        ],
        "assignee": "dev-3",
    },
    "product-service": {
        "project": "PROD",
        "component": "catalog search, recommendations, and inventory",
        "release_topics": [
            "catalog search indexing",
            "recommendation ranking",
            "inventory reservation sync",
            "category navigation",
            "product image delivery",
            "attribute filtering",
            "bulk catalog imports",
            "price freshness checks",
            "search synonym updates",
        ],
        "incident_topics": [
            "catalog search 500s",
            "stale inventory counts",
            "recommendation latency",
            "missing product images",
            "category navigation errors",
            "attribute filter mismatches",
            "catalog import failures",
            "stale product prices",
            "search index lag",
        ],
        "assignee": "dev-4",
    },
    "order-service": {
        "project": "ORD",
        "component": "order processing, fulfillment, and returns",
        "release_topics": [
            "split shipment orchestration",
            "fulfillment status webhooks",
            "return authorization rules",
            "order event replay",
            "carrier tracking sync",
            "partial cancellation handling",
            "warehouse allocation",
            "order confirmation delivery",
            "backorder state transitions",
        ],
        "incident_topics": [
            "fulfillment status lag",
            "order event duplication",
            "return authorization failures",
            "carrier tracking delays",
            "partial cancellation errors",
            "warehouse allocation timeouts",
            "order confirmation delivery",
            "backorder state mismatches",
            "split shipment failures",
        ],
        "assignee": "dev-5",
    },
}


def _expand_service_records() -> None:
    """Guarantee a useful baseline of correlated records for every project."""
    deployment_number = max(int(item["id"].split("-")[1]) for item in DEPLOYMENTS)
    incident_number = max(int(item["id"].split("-")[1]) for item in INCIDENTS)
    deployments_by_service = {service["id"]: [] for service in SERVICES}
    for deployment in DEPLOYMENTS:
        deployments_by_service.setdefault(deployment["service"], []).append(deployment)

    for service in SERVICES:
        service_id = service["id"]
        context = _SERVICE_CONTEXT[service_id]
        existing_deployments = deployments_by_service[service_id]
        while len(existing_deployments) < 10:
            index = len(existing_deployments)
            deployment_number += 1
            status = ("failed", "rolled_back", "in_progress", "success")[index % 4]
            environment = "staging" if index % 3 == 0 else "production"
            deployment = {
                "id": f"DEP-{deployment_number}",
                "service": service_id,
                "environment": environment,
                "version": f"v{index + 1}.2.{index}",
                "status": status,
                "deployed_by": context["assignee"],
                "deployed_at": f"2026-08-{23 - index:02d}T{10 + index:02d}:00:00Z",
                "duration_seconds": 110 + index * 17,
                "linked_story": f"{context['project']}-{600 + index}",
                "linked_pr": 150 + deployment_number - 1007,
                "notes": f"{context['release_topics'][index - 1]} release for {context['component']}.",
            }
            DEPLOYMENTS.append(deployment)
            existing_deployments.append(deployment)

        existing_incidents = [item for item in INCIDENTS if item["affected_service"] == service_id]
        while len(existing_incidents) < 10:
            index = len(existing_incidents)
            incident_number += 1
            status = ("resolved", "investigating", "open")[index % 3]
            linked_deployment = existing_deployments[index % len(existing_deployments)]
            incident = {
                "id": f"INC-{incident_number}",
                "title": f"{context['incident_topics'][index - 1].capitalize()} affecting {context['project']}",
                "severity": ("P2", "P3", "P4", "P1")[index % 4],
                "status": status,
                "affected_service": service_id,
                "assignee": context["assignee"],
                "opened_at": f"2026-08-{22 - index:02d}T{8 + index:02d}:15:00Z",
                "resolved_at": f"2026-08-{22 - index:02d}T{12 + index:02d}:00:00Z" if status == "resolved" else None,
                "linked_deployment": linked_deployment["id"],
                "description": f"Monitoring detected {context['incident_topics'][index - 1]} in the {context['component']}.",
            }
            INCIDENTS.append(incident)
            existing_incidents.append(incident)


_expand_service_records()
