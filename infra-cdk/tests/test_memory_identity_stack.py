"""CDK synth assertion tests for MahaloMemoryIdentityStack (Task 5), offline.

Mirrors ``test_gateway_stack.py``'s ``Template.from_stack`` style. Asserts the
STM-only Memory (no MemoryStrategies, EventExpiryDuration == 30), one
WorkloadIdentity, one ApiKeyCredentialProvider, the MemoryId / provider-name
outputs, and the no-echo API-key parameter.
"""

import aws_cdk as cdk
from aws_cdk import assertions

from mahalo_infra.memory_identity_stack import MahaloMemoryIdentityStack

_ENV = cdk.Environment(account="123456789012", region="us-east-1")


def _template():
    app = cdk.App()
    stack = MahaloMemoryIdentityStack(app, "MahaloMemoryIdentityStack", env=_ENV)
    return assertions.Template.from_stack(stack)


def test_single_stm_memory_expiry_30_no_strategies():
    tmpl = _template()
    tmpl.resource_count_is("AWS::BedrockAgentCore::Memory", 1)
    memories = tmpl.find_resources("AWS::BedrockAgentCore::Memory")
    (memory,) = memories.values()
    props = memory["Properties"]
    assert props["EventExpiryDuration"] == 30
    # STM only: no long-term strategies.
    assert "MemoryStrategies" not in props


def test_single_workload_identity():
    tmpl = _template()
    tmpl.resource_count_is("AWS::BedrockAgentCore::WorkloadIdentity", 1)


def test_single_api_key_credential_provider():
    tmpl = _template()
    tmpl.resource_count_is("AWS::BedrockAgentCore::ApiKeyCredentialProvider", 1)


def test_memory_id_and_provider_name_outputs_exist():
    tmpl = _template()
    outputs = tmpl.to_json().get("Outputs", {})
    assert "MemoryId" in outputs
    assert "JiraApiKeyProviderName" in outputs
    assert "WorkloadIdentityArn" in outputs


def test_api_key_parameter_is_no_echo():
    tmpl = _template()
    params = tmpl.to_json().get("Parameters", {})
    assert "JiraApiKey" in params
    assert params["JiraApiKey"]["NoEcho"] is True
