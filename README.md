# mahalo-agentcore

AgentCore/Strands rewrite of **mahalo-dock**. This project re-engineers the existing
mahalo-dock application onto the Amazon Bedrock AgentCore stack and the Strands Agents SDK,
replacing the prior LangGraph/LangChain approach.

> mahalo-dock remains the untouched fallback demo. Nothing in this project modifies it.

## Target architecture

- **Strands agent** hosted on **AgentCore Runtime**.
- **4 mock systems** (Jira, Confluence, GitHub, ServiceNow) implemented as **AWS Lambdas**,
  exposed behind **AgentCore Gateway** as MCP tools.
- **AgentCore Memory** for session state.
- **AgentCore Identity** for tool credentials.
- **Self-hosted Gitea** on an always-on host (the GitHub-mock Lambda talks to Gitea).
- **Next.js frontend** calling a thin API that forwards to the AgentCore Runtime.
- **AWS CDK in Python** for infrastructure-as-code.
- **Model**: Bedrock Claude Sonnet 4.5 (`us.anthropic.claude-sonnet-4-5-20250929-v1:0`).

## AWS target

| Setting  | Value             |
| -------- | ----------------- |
| Profile  | `lava`            |
| Region   | `us-east-1`       |
| Account  | `<AWS_ACCOUNT_ID>`    |

## Repository layout

| Path             | Purpose                                              |
| ---------------- | ---------------------------------------------------- |
| `agent/`         | Strands agent implementation                         |
| `tools-lambdas/` | Mock system Lambdas (Jira/Confluence/GitHub/ServiceNow) |
| `api/`           | Thin API that forwards to the AgentCore Runtime      |
| `frontend/`      | Next.js frontend                                     |
| `infra-cdk/`     | AWS CDK (Python) infrastructure                      |
| `gitea/`         | Self-hosted Gitea config/assets                      |
| `docs/`          | Architecture and plan documents                      |
| `scripts/`       | Operational scripts (capability checks, etc.)        |

## Capability check

Run the read-only AgentCore capability check before starting infrastructure work:

```powershell
pwsh ./scripts/verify-agentcore.ps1 -Profile lava -Region us-east-1
```

See `docs/ARCHITECTURE.md` for the target architecture and `docs/PLAN.md` for the phased plan.
