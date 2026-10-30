"""CDK synth assertion tests for MahaloKeepWarmStack (latency follow-up #3), offline.

Option A: a scheduled EventBridge rule fires an inline (Docker-free) Lambda shim
that pings the Runtime with a trivial InvokeAgentRuntime call. These tests assert
the keep-warm resources synthesize with the correct cadence and target and that
the shim is granted InvokeAgentRuntime scoped to the Runtime (and no per-user
action), all without Docker so the offline synth gate stays green.
"""

import aws_cdk as cdk
from aws_cdk import assertions

from mahalo_infra.keepwarm_stack import MahaloKeepWarmStack
from mahalo_infra.memory_identity_stack import MahaloMemoryIdentityStack
from mahalo_infra.runtime_stack import MahaloRuntimeStack

_ENV = cdk.Environment(account="123456789012", region="us-east-1")


def _keepwarm():
    app = cdk.App()
    memory = MahaloMemoryIdentityStack(app, "MahaloMemoryIdentityStack", env=_ENV)
    runtime = MahaloRuntimeStack(
        app, "MahaloRuntimeStack", memory_stack=memory, env=_ENV
    )
    keepwarm = MahaloKeepWarmStack(
        app, "MahaloKeepWarmStack", runtime_stack=runtime, env=_ENV
    )
    return assertions.Template.from_stack(keepwarm), app


def test_single_python313_lambda():
    tmpl, _ = _keepwarm()
    tmpl.resource_count_is("AWS::Lambda::Function", 1)
    tmpl.has_resource_properties(
        "AWS::Lambda::Function", {"Runtime": "python3.13"}
    )


def test_eventbridge_rule_cadence():
    tmpl, _ = _keepwarm()
    tmpl.resource_count_is("AWS::Events::Rule", 1)
    # Every 10 min, Mon–Fri, 13:00–22:50 UTC (demo window).
    tmpl.has_resource_properties(
        "AWS::Events::Rule",
        {"ScheduleExpression": "cron(0/10 13-22 ? * MON-FRI *)"},
    )


def test_rule_targets_the_lambda_with_permission():
    tmpl, _ = _keepwarm()
    # The rule has a Lambda target (Arn present in its Targets list).
    rules = tmpl.find_resources("AWS::Events::Rule")
    (rule,) = rules.values()
    rule_targets = rule["Properties"]["Targets"]
    assert len(rule_targets) == 1
    assert "Arn" in rule_targets[0]
    # EventBridge is permitted to invoke the shim.
    tmpl.resource_count_is("AWS::Lambda::Permission", 1)
    tmpl.has_resource_properties(
        "AWS::Lambda::Permission",
        {"Principal": "events.amazonaws.com"},
    )


def test_shim_can_invoke_runtime_only():
    tmpl, _ = _keepwarm()
    policies = tmpl.find_resources("AWS::IAM::Policy")
    actions = set()
    for policy in policies.values():
        for stmt in policy["Properties"]["PolicyDocument"]["Statement"]:
            act = stmt["Action"]
            actions.update(act if isinstance(act, list) else [act])
    assert "bedrock-agentcore:InvokeAgentRuntime" in actions
    # Identity off in the MVP: the per-user action is NOT granted.
    assert "bedrock-agentcore:InvokeAgentRuntimeForUser" not in actions


def test_shim_env_has_runtime_arn():
    tmpl, _ = _keepwarm()
    fns = tmpl.find_resources("AWS::Lambda::Function")
    (fn,) = fns.values()
    env = fn["Properties"]["Environment"]["Variables"]
    assert "MAHALO_RUNTIME_ARN" in env


def test_inline_lambda_stages_no_container_image_asset():
    _, app = _keepwarm()
    assembly = app.synth()
    stack_art = assembly.get_stack_by_name("MahaloKeepWarmStack")
    image_assets = [
        a for a in stack_art.assets if a.get("packaging") == "container-image"
    ]
    assert image_assets == []
