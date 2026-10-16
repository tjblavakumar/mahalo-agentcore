# Phased Plan

The rewrite proceeds in incremental tasks. Each task leaves the project in a working,
demonstrable state before the next begins.

## Task 0 - Verification and skeleton (DONE)

Verify the toolchain and AWS/AgentCore capabilities, then scaffold the repository: directory
structure, `.gitignore`, `README.md`, architecture and plan docs, and a read-only AgentCore
capability-check script. Initialize git and push the skeleton to the remote.

## Task 1 - Strands agent (local) vs existing mocks (CODE-COMPLETE)

Build the first version of the Strands agent running locally, wired to the existing mock
systems so we can exercise end-to-end reasoning before any AWS hosting is introduced.

Progress: implemented under `agent/` — env-driven config, a Bedrock-backed Strands agent
(Claude Sonnet 4.5, 300s read timeout, `lava` profile), ported prompts, 19 read-only tools
over Jira/Confluence/GitHub/ServiceNow, a `python -m agent.chat` CLI/REPL (dev-6 identity),
and unit + live-integration tests. Zero LangChain. Offline verification recorded in
`docs/.agents/tasks/task1-verification.md` (unit 13/13 pass; full suite passes with the live
integration test skipping while the tunnel is down; agent builds without creds). The live
REPL/Bedrock/tunnel run remains for the user. Write/propose/approve is deferred to Task 2.

## Task 2 - Propose/approve in Strands

Implement the propose/approve interaction pattern inside the Strands agent so changes are
surfaced for approval before any action is taken.

## Task 3 - Mocks as Lambdas

Reimplement the four mock systems (Jira, Confluence, GitHub, ServiceNow) as AWS Lambdas,
keeping their behavior equivalent to the local mocks.

## Task 4 - Gateway MCP

Place the Lambdas behind AgentCore Gateway and expose them as MCP tools the agent can call.

## Task 5 - Memory and Identity

Add AgentCore Memory for session state and AgentCore Identity for tool credentials.

## Task 6 - Runtime hosting

Host the Strands agent on AgentCore Runtime and route traffic to it through the thin API.

## Task 7 - Gitea and frontend hosting

Stand up self-hosted Gitea on an always-on host and deploy the Next.js frontend.

## Task 8 - Re-deployable CDK and teardown

Harden the AWS CDK (Python) stacks so the environment can be deployed and torn down cleanly
and repeatably.

## Task 9 - Docs

Finalize documentation covering architecture, operations, and demo walkthrough.
