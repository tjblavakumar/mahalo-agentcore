"""Rich e-commerce documentation seed data for Mock Confluence service."""

SPACES = [
    {
        "id": "ENG",
        "name": "Engineering",
        "description": "Technical documentation, ADRs, and architecture guides",
    },
    {
        "id": "SEC",
        "name": "Security & Compliance",
        "description": "Security policies, compliance docs, and audit reports",
    },
    {
        "id": "PROD",
        "name": "Product",
        "description": "Product requirements, roadmaps, and sprint retrospectives",
    },
    {
        "id": "API",
        "name": "API Documentation",
        "description": "API specs, integration guides, and developer docs",
    },
]

PAGES = [
    # === Engineering Space ===
    {
        "id": "ENG-001",
        "space_id": "ENG",
        "title": "ADR-001: Microservices Architecture",
        "author": "Marcus Chen",
        "last_updated": "2026-07-15",
        "content": """# ADR-001: Microservices Architecture

## Status
Accepted

## Context
Our e-commerce platform has grown significantly. The monolithic architecture is becoming difficult to scale and deploy independently.

## Decision
We will decompose the monolith into the following microservices:
- **Payment Service** - Handles all payment processing (Stripe, Apple Pay, Google Pay)
- **Cart Service** - Shopping cart management and pricing
- **Auth Service** - User authentication and authorization
- **Product Service** - Product catalog and inventory
- **Order Service** - Order processing and fulfillment

Each service will:
- Own its own database (database-per-service pattern)
- Communicate via REST APIs for synchronous calls
- Use event bus (RabbitMQ) for async events
- Be independently deployable

## Consequences
- Teams can deploy independently
- Increased operational complexity
- Need for distributed tracing (OpenTelemetry)
- API gateway required for client-facing APIs
""",
    },
    {
        "id": "ENG-002",
        "space_id": "ENG",
        "title": "ADR-002: Event-Driven Communication",
        "author": "Sarah Johnson",
        "last_updated": "2026-07-20",
        "content": """# ADR-002: Event-Driven Communication Between Services

## Status
Accepted

## Context
Services need to react to changes in other services without tight coupling. For example, when a payment is confirmed, the order service needs to update order status.

## Decision
- Use RabbitMQ as the message broker
- Publish domain events on state changes
- Services subscribe to relevant events
- Events are immutable and include full context

### Key Events:
- `payment.confirmed` - Payment service -> Order service
- `order.created` - Order service -> Inventory service
- `inventory.low_stock` - Inventory -> Notification service
- `user.registered` - Auth -> Email service

## Consequences
- Loose coupling between services
- Eventual consistency (not immediate)
- Need for idempotent event handlers
- Dead letter queue for failed processing
""",
    },
    {
        "id": "ENG-003",
        "space_id": "ENG",
        "title": "Payment Service Technical Design",
        "author": "Marcus Chen",
        "last_updated": "2026-08-01",
        "content": """# Payment Service - Technical Design

## Overview
The payment service handles all financial transactions for the e-commerce platform.

## Technology Stack
- **Language**: Python 3.11 + FastAPI
- **Database**: PostgreSQL (for ACID transactions)
- **Cache**: Redis (for idempotency keys)
- **Payment Providers**: Stripe (primary), PayPal (secondary)

## Architecture
```
Client -> API Gateway -> Payment Service -> Stripe API
                                         -> PayPal API
                                         -> PostgreSQL
                                         -> Redis
                                         -> RabbitMQ (events)
```

## Key Features
1. **Idempotent Payments** - Every payment request has a unique idempotency key
2. **Webhook Processing** - Async processing of payment provider webhooks
3. **Retry Logic** - Exponential backoff for failed payment attempts
4. **Audit Trail** - Complete log of all payment state transitions
5. **Multi-Currency** - Support for USD, EUR, GBP, JPY

## Security
- PCI DSS Level 1 compliance
- No raw card data stored
- All card operations use Stripe tokenization
- TLS 1.3 for all connections
- IP whitelisting for webhook endpoints

## Deployment
- Kubernetes deployment with 3 replicas
- Blue-green deployment strategy
- Health checks every 10 seconds
- Auto-scaling based on transaction volume
""",
    },
    {
        "id": "ENG-004",
        "space_id": "ENG",
        "title": "Database Migration Strategy",
        "author": "Raj Patel",
        "last_updated": "2026-07-25",
        "content": """# Database Migration Strategy

## Approach
We use Alembic for schema migrations with the following rules:

1. **Forward-only migrations** - No rollback scripts in production
2. **Backward-compatible changes** - New columns must be nullable or have defaults
3. **Zero-downtime deployments** - Migrations must not lock tables for extended periods
4. **Data migrations separate** - Schema changes and data migrations are separate steps

## Migration Checklist
- [ ] Migration tested locally
- [ ] Migration tested against production-size dataset
- [ ] Estimated execution time < 30 seconds
- [ ] No breaking changes to existing queries
- [ ] Rollback plan documented (even if manual)

## Naming Convention
`{timestamp}_{description}.py`
Example: `20260725_add_currency_column_to_payments.py`
""",
    },
    {
        "id": "ENG-005",
        "space_id": "ENG",
        "title": "SAML 2.0 SSO - Technical Design",
        "author": "Lava Dev",
        "last_updated": "2026-08-18",
        "content": """# SAML 2.0 SSO - Technical Design

## Overview
Enterprise customers require single sign-on through their own identity providers (Okta, Azure AD). This document describes the SAML 2.0 integration for the auth service. Linked to AUTH-306.

## Goals
- Support both IdP-initiated and SP-initiated login flows
- Just-in-time (JIT) user provisioning on first login
- Per-organization IdP configuration
- No passwords stored for SSO users

## Flow
```
User -> App -> Auth Service (SP) -> Customer IdP -> SAML Assertion -> Auth Service -> Session
```

## Components
1. **SP Metadata Endpoint** - Exposes our service provider metadata for IdP configuration
2. **Assertion Consumer Service (ACS)** - Receives and validates SAML assertions
3. **JIT Provisioning** - Creates a user record on first successful login, mapping SAML attributes to profile fields
4. **Admin Configuration UI** - Lets an org admin register their IdP metadata

## Security Considerations
- Validate assertion signature against the IdP's published certificate
- Enforce assertion `NotBefore` / `NotOnOrAfter` conditions
- Reject unsolicited responses without a matching request ID (SP-initiated)
- Bind sessions to the authenticated `NameID`

## Open Questions
- Encrypted assertions: required for phase 1 or phase 2?
- Group-to-role mapping: how granular for the first release?
""",
    },
    # === Security & Compliance Space ===
    {
        "id": "SEC-001",
        "space_id": "SEC",
        "title": "PCI DSS Compliance Requirements",
        "author": "Raj Patel",
        "last_updated": "2026-08-10",
        "content": """# PCI DSS Compliance Requirements

## Overview
As a Level 1 merchant processing >6M transactions/year, we must comply with all PCI DSS v4.0 requirements.

## Key Requirements

### Requirement 3: Protect Stored Account Data
- **3.4.1**: PAN is masked when displayed (show only last 4 digits)
- **3.5.1**: PAN is rendered unreadable when stored (we use Stripe tokenization, no PAN stored)
- **3.6.1**: Cryptographic keys are managed with a documented process

### Requirement 6: Develop Secure Systems
- **6.2.4**: Code reviews for all changes to payment-related code
- **6.3.1**: Security vulnerabilities identified and ranked by risk
- **6.4.1**: Public-facing web apps protected against attacks (WAF deployed)

### Requirement 8: Identify Users and Authenticate Access
- **8.3.1**: MFA for all administrative access to payment systems
- **8.3.6**: Passwords minimum 12 characters for payment system access
- **8.6.1**: System/service accounts managed with restricted privileges

## Audit Schedule
- **Quarterly**: Vulnerability scans (ASV)
- **Semi-annually**: Penetration testing
- **Annually**: Full PCI DSS assessment by QSA

## Current Status
- Last audit: July 2026 (PASSED)
- Next audit: January 2027
- Open findings: 2 (low severity)
  - Finding 1: Log retention policy needs update (30 days -> 90 days)
  - Finding 2: Service account password rotation from 90 days to 60 days
""",
    },
    {
        "id": "SEC-002",
        "space_id": "SEC",
        "title": "Security Incident Response Plan",
        "author": "Raj Patel",
        "last_updated": "2026-07-30",
        "content": """# Security Incident Response Plan

## Severity Levels

### P1 - Critical
- Data breach confirmed
- Payment system compromised
- All hands response within 15 minutes

### P2 - High
- Suspected breach / anomalous activity
- Service degradation in security controls
- Response within 1 hour

### P3 - Medium
- Vulnerability discovered in production
- Failed security audit finding
- Response within 24 hours

## Response Team
- **Incident Commander**: CTO (backup: VP Engineering)
- **Technical Lead**: Senior SRE on-call
- **Communications**: Head of Customer Success
- **Legal**: General Counsel

## Response Steps
1. **Detect** - Alert triggered via monitoring
2. **Contain** - Isolate affected systems
3. **Investigate** - Determine scope and root cause
4. **Remediate** - Fix the vulnerability
5. **Recover** - Restore normal operations
6. **Report** - Post-incident review within 48 hours
""",
    },
    {
        "id": "SEC-003",
        "space_id": "SEC",
        "title": "Authentication Security Guidelines",
        "author": "Raj Patel",
        "last_updated": "2026-08-05",
        "content": """# Authentication Security Guidelines

## Password Policy
- Minimum 12 characters
- Must contain uppercase, lowercase, number, and special character
- Bcrypt hashing with cost factor 12
- No password reuse (last 10 passwords)

## Session Management
- JWT tokens with 1-hour expiration
- Refresh tokens with 7-day expiration
- Secure, HttpOnly, SameSite cookies
- Session invalidation on password change

## Multi-Factor Authentication
- TOTP-based (Google Authenticator, Authy)
- Required for: admin accounts, payment system access
- Optional but recommended for: all user accounts
- Backup codes: 10 single-use codes generated on setup

## OAuth Integration
- Supported providers: Google, GitHub, Microsoft
- Scopes limited to email and profile
- Account linking requires email verification
- Token stored encrypted at rest

## Rate Limiting
- Login: 5 attempts / 15 minutes / IP
- Registration: 3 accounts / hour / IP
- Password reset: 3 requests / hour / account
- API: 1000 requests / minute / user
""",
    },
    # === Product Space ===
    {
        "id": "PROD-001",
        "space_id": "PROD",
        "title": "Q3 2026 Product Roadmap",
        "author": "Alice Product",
        "last_updated": "2026-08-01",
        "content": """# Q3 2026 Product Roadmap

## Theme: International Expansion & Payment Flexibility

### July 2026 (Completed)
- [x] Apple Pay integration
- [x] Cart persistence across sessions
- [x] Elasticsearch product search
- [x] Order tracking real-time updates

### August 2026 (In Progress)
- [ ] Google Pay integration
- [ ] Multi-currency support (EUR, GBP, JPY)
- [ ] Product recommendations engine
- [ ] Two-factor authentication
- [ ] Split order fulfillment

### September 2026 (Planned)
- [ ] Cryptocurrency payments (BTC, ETH)
- [ ] Fraud detection ML model
- [ ] Internationalization (i18n) for storefront
- [ ] Advanced analytics dashboard
- [ ] Mobile app push notifications

## Key Metrics Targets
- Payment success rate: >98% (currently 96.5%)
- Cart abandonment rate: <65% (currently 72%)
- Search relevance score: >0.85 (currently 0.79)
- Page load time: <2s (currently 2.3s)

## Dependencies
- Multi-currency requires Stripe Atlas account (approved)
- Recommendations engine needs 6 months of user behavior data (available)
- Fraud detection needs labeled dataset (in preparation)
""",
    },
    {
        "id": "PROD-002",
        "space_id": "PROD",
        "title": "Sprint 24 Retrospective - Payment Team",
        "author": "Marcus Chen",
        "last_updated": "2026-08-22",
        "content": """# Sprint 24 Retrospective - Payment Team

## Summary
Sprint Goal: Implement Google Pay and multi-currency foundation
Velocity: 34 points (planned), 26 points (completed)

## What Went Well
- Google Pay integration smoother than expected
- Payment retry mechanism well-received by QA
- Good collaboration with cart team on currency handling

## What Didn't Go Well
- Multi-currency story underestimated (13 points wasn't enough)
- Exchange rate API had unexpected rate limiting
- Payment analytics dashboard review took too long

## Action Items
1. Break down multi-currency into smaller stories for next sprint
2. Set up exchange rate API caching layer
3. Establish SLA for PR reviews (max 24 hours)

## Carry Over
- PAY-107: Multi-currency support (partially complete, needs 2 more days)
""",
    },
    {
        "id": "PROD-003",
        "space_id": "PROD",
        "title": "Feature Requirements: Multi-Currency Support",
        "author": "Alice Product",
        "last_updated": "2026-08-10",
        "content": """# Feature Requirements: Multi-Currency Support

## Business Context
25% of our traffic comes from international users. Currently we only support USD, leading to cart abandonment for international customers.

## User Stories
1. As a customer, I want to see prices in my local currency so I can understand costs without mental conversion
2. As a customer, I want to pay in my local currency to avoid foreign transaction fees
3. As a merchant, I want to receive settlements in USD regardless of customer currency

## Supported Currencies (Phase 1)
- EUR (Euro) - Covers EU customers (15% of international traffic)
- GBP (British Pound) - UK customers (5% of international traffic)
- JPY (Japanese Yen) - Japan customers (3% of international traffic)

## Technical Requirements
- Exchange rates updated every 15 minutes from OpenExchangeRates API
- Rates cached in Redis to handle API downtime
- Price displayed in customer's currency, charged in that currency
- Settlement converted to USD at time of daily batch
- Rounding rules per currency (JPY has no decimal places)

## Acceptance Criteria
- Currency auto-detected from user's browser locale
- Currency selector visible on all pages
- Cart totals recalculate on currency change
- Order confirmation shows both customer currency and USD equivalent
- Exchange rate at time of purchase locked for 15 minutes

## Timeline
- Design: Sprint 24 (done)
- Implementation: Sprint 24-25
- QA: Sprint 25
- Launch: Sprint 26
""",
    },
    # === API Documentation Space ===
    {
        "id": "API-001",
        "space_id": "API",
        "title": "Payment Service API Specification",
        "author": "Marcus Chen",
        "last_updated": "2026-08-12",
        "content": """# Payment Service API Specification

## Base URL
`https://api.ecommerce.io/v1/payments`

## Authentication
Bearer token required for all endpoints.

## Endpoints

### POST /payments
Create a new payment intent.

**Request:**
```json
{
  "amount": 9999,
  "currency": "usd",
  "payment_method": "card",
  "customer_id": "cust_123",
  "metadata": {"order_id": "ord_456"}
}
```

**Response (201):**
```json
{
  "id": "pay_789",
  "status": "requires_confirmation",
  "amount": 9999,
  "currency": "usd",
  "client_secret": "pi_xxx_secret_yyy"
}
```

### POST /payments/{id}/confirm
Confirm a payment intent.

### POST /payments/{id}/refund
Initiate a refund (full or partial).

**Request:**
```json
{
  "amount": 5000,
  "reason": "customer_request"
}
```

### GET /payments/{id}
Get payment details.

### GET /payments?customer_id={id}&status={status}
List payments with filters.

## Webhooks
Configure webhook URL in dashboard. Events:
- `payment.succeeded`
- `payment.failed`
- `payment.refunded`

## Error Codes
- `insufficient_funds` - Card has insufficient funds
- `card_declined` - Card was declined
- `expired_card` - Card has expired
- `processing_error` - Temporary processing error (retry)
""",
    },
    {
        "id": "API-002",
        "space_id": "API",
        "title": "Cart Service API Specification",
        "author": "Sarah Johnson",
        "last_updated": "2026-08-08",
        "content": """# Cart Service API Specification

## Base URL
`https://api.ecommerce.io/v1/cart`

## Endpoints

### GET /cart
Get current user's cart.

**Response:**
```json
{
  "id": "cart_123",
  "items": [
    {
      "product_id": "prod_456",
      "name": "Wireless Headphones",
      "quantity": 2,
      "unit_price": 7999,
      "total": 15998
    }
  ],
  "subtotal": 15998,
  "tax": 1440,
  "shipping": 599,
  "total": 18037,
  "currency": "usd",
  "coupon": null
}
```

### POST /cart/items
Add item to cart.

### PUT /cart/items/{product_id}
Update item quantity.

### DELETE /cart/items/{product_id}
Remove item from cart.

### POST /cart/coupon
Apply coupon code.

### DELETE /cart/coupon
Remove applied coupon.

## Events Published
- `cart.item_added`
- `cart.item_removed`
- `cart.abandoned` (after 24h inactivity)
""",
    },
    {
        "id": "API-003",
        "space_id": "API",
        "title": "Integration Guide: Third-Party Developers",
        "author": "Emily Zhang",
        "last_updated": "2026-08-15",
        "content": """# Integration Guide for Third-Party Developers

## Getting Started

### 1. Register for API Access
Create a developer account at https://developers.ecommerce.io

### 2. Get API Keys
- **Test key**: Use for development (prefix: `test_`)
- **Live key**: Use for production (prefix: `live_`)

### 3. Authentication
Include your API key in the Authorization header:
```
Authorization: Bearer your_api_key_here
```

## Rate Limits
- Test: 100 requests/minute
- Live: 1000 requests/minute
- Burst: 50 requests/second

## Webhooks
1. Register webhook URL in developer dashboard
2. Verify webhook signatures using shared secret
3. Respond with 200 within 5 seconds
4. Events are retried 3 times with exponential backoff

## SDKs
- Python: `pip install ecommerce-sdk`
- Node.js: `npm install @ecommerce/sdk`
- Ruby: `gem install ecommerce-ruby`

## Support
- Documentation: https://docs.ecommerce.io
- Status page: https://status.ecommerce.io
- Email: developers@ecommerce.io
""",
    },
]
