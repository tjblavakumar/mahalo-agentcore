"""mahalo thin stateless API — forwards to the AgentCore Runtime (Task 6).

This package is a pure forwarder: no business logic, no second agent, and it does
NOT import ``agent/`` or any Strands/tool/LangChain code. It speaks only the small
JSON contract of ``docs/.agents/tasks/task6-design.md`` §A.3 and calls the
``bedrock-agentcore`` data-plane ``InvokeAgentRuntime``.
"""
