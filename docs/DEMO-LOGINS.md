# MAHALO demo — login sheet & run guide

Everything you need to drive the live demo: who to log in as, where, and what to
ask so the agent shows all four systems working together with real Gitea.

## 1. Mahalo UI — persona logins

Open the demo UI and log in as any persona. The agent tailors answers to the
persona's role and identity. Switch personas freely to show different views.

| Persona | Username | Password | Who the agent acts as | Role flavor |
|---|---|---|---|---|
| Product Manager | `pm` | `pm123` | Marcus Chen (dev-1) | Roadmap / sprint / cross-project synthesis |
| Developer | `dev` | `dev123` | Lava Dev (dev-6) | My work: stories, branches, PRs, incidents |
| Executive | `exec` | `exec123` | David Kim (dev-5) | High-level status, risk, delivery health |

**Mahalo UI:** https://dw28e5je2s7b9.cloudfront.net

## 2. Gitea — single admin login (see every persona's git activity)

By design there is ONE Gitea user. Everything the agent writes (branches,
commits, PRs) is owned by this admin, and each change is labeled in its commit
message / PR title with the persona who made it. Log in here to show that the
agent's writes are landing in a real git server.

| Field | Value |
|---|---|
| Gitea URL | https://d3ec76atxiij9a.cloudfront.net/ |
| Username | `mahalo_admin` |
| Password | stored in SSM SecureString `/mahalo/gitea/admin-password` (not written here) |

To read it (needs AWS credentials for the account):
`aws ssm get-parameter --name /mahalo/gitea/admin-password --with-decryption --query Parameter.Value --output text`

Seeded repos (match the 5 Jira projects): `payment-service`, `cart-service`,
`auth-service`, `product-service`, `order-service` — each with feature branches
and open PRs labeled by author, e.g. *"feat: Google Pay integration — authored by
Marcus Chen (Product Manager) [PAY-105]"*.

> The agent is in **real Gitea mode**: reads (list repos / PRs / branches) and
> writes (create branch / commit / open PR, behind the approval gate) all go to
> this live Gitea. A write you approve in Mahalo appears here immediately.

## 3. The four connected systems

| System | Backing | What it holds |
|---|---|---|
| Jira | mock Lambda + DynamoDB | 5 projects (PAY/CART/AUTH/PROD/ORD), sprints, stories |
| Confluence | mock Lambda + DynamoDB | project docs / pages |
| ServiceNow | mock Lambda + DynamoDB | incidents / change requests |
| GitHub | **real Gitea** (EC2) | repos, branches, commits, PRs |

All four are exposed to the agent as MCP tools through AgentCore Gateway; the
agent reasons across them in one turn.

## 4. Suggested demo script (shows all four working together)

1. **Log in as Developer (`dev`/`dev123`).**
   - Ask: *"What am I working on right now?"* → the agent pulls your in-progress
     Jira stories, their linked PRs in Gitea, and any related ServiceNow
     incidents — one answer spanning three systems.
   - Ask: *"Show the open pull requests for payment-service with links."* → real
     Gitea PRs, each with the author label and a clickable CloudFront link.
   - Ask: *"Create a branch feature/demo-xyz off main in payment-service."* → the
     agent proposes the write and waits. **Approve** it. Then open Gitea
     (mahalo_admin) and show the branch is really there.

2. **Switch to Product Manager (`pm`/`pm123`).**
   - Open the **Dashboard** → the agent synthesizes a cross-project view (pick
     the projects to include; defaults to PAY for a fast first render).
   - Ask: *"Give me a status summary across all my projects."* → sprint progress
     from Jira, open PRs from Gitea, open incidents from ServiceNow, blended.

3. **Switch to Executive (`exec`/`exec123`).**
   - Ask: *"What's the delivery risk this sprint?"* → a higher-level synthesis
     across the same systems, framed for an exec.

4. **Show the proof in Gitea.** Log into https://d3ec76atxiij9a.cloudfront.net/
   as `mahalo_admin` and walk the repos/PRs/branches — including the branch you
   just created live — so the audience sees the agent's writes are real.

## 5. Notes / known cosmetics (demo-safe)

- Real Gitea metrics (additions/files) reflect what's actually seeded, so they
  differ slightly from the old mock's exact numbers. The story is identical.
- The agent tags every Gitea PR author with `(dev-6)` because all git activity is
  owned by the one admin user; the author NAME in each PR title is correct. This
  is a deliberate consequence of the single-admin-user demo design.
- Gitea is reachable only over its HTTPS CloudFront URL (port 3000 is blocked by
  corporate networks). Use the https://d3ec76atxiij9a.cloudfront.net/ URL, not
  the raw EC2 host.
