# mahalo agent — AgentCore Runtime container image (Task 6).
#
# linux/arm64 is the AgentCore Runtime container contract, grounded in the
# installed CDK L1 docstring (infra-cdk/.venv/.../aws_bedrockagentcore/__init__.py):
# container deployment says developers build ARM-compatible containers, and the
# code-deploy alternative requires a Linux arm64 dependency archive. See
# docs/.agents/tasks/task6-design.md §A.6.
FROM --platform=linux/arm64 python:3.13-slim

WORKDIR /app

# Install the agent's deps first for layer caching. bedrock-agentcore==1.24.1
# pulls uvicorn + starlette transitively, so the ASGI harness ships even though
# the dev venv happens not to have uvicorn installed.
COPY agent/requirements.txt ./agent/requirements.txt
RUN pip install --no-cache-dir -r agent/requirements.txt

# Copy the whole agent package (25 tools + the runtime harness).
COPY agent/ ./agent/

# NOTE (design §A.6 / Finding 1): do NOT set AWS_PROFILE. agent/config.py then
# resolves the "lava" default; _build_bedrock_model checks botocore
# available_profiles and, because "lava" is absent in the container, builds a
# profile-less boto3 Session so boto3 uses the default (execution-role) chain.

EXPOSE 8080
CMD ["python", "-m", "agent.runtime_app"]
