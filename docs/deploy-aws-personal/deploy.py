#!/usr/bin/env python3
"""deploy.py - deploy MAHALO (mahalo-agentcore) to YOUR OWN AWS account.

Cross-platform (Windows / macOS / Linux), Python standard library only. It drives
the existing CDK app in infra-cdk/, the Next.js frontend build, and the AWS CLI.
It never stores credentials and writes nothing outside this repo and the OS temp
dir. Run it from anywhere:

    python docs/deploy-aws-personal/deploy.py --help

Typical first run (see RUNBOOK.md for the full, annotated version):

    python deploy.py preflight --profile personal --region us-east-1
    python deploy.py bootstrap --profile personal --region us-east-1
    python deploy.py deploy    --profile personal --region us-east-1
    python deploy.py verify    --profile personal --region us-east-1

Scope of this package: the MOCK-git version (Jira / Confluence / ServiceNow /
GitHub are all mock Lambdas). Real Gitea is intentionally NOT included.

Safety: every command that changes AWS shows the target account/region/principal
and asks you to type "yes" (or pass --yes). Use --expect-account to refuse to run
against any other account. Use --dry-run to print the commands without running them.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

# --------------------------------------------------------------------------- paths
HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent  # docs/deploy-aws-personal -> docs -> <repo root>
INFRA = REPO / "infra-cdk"
FRONTEND = REPO / "frontend"

# --------------------------------------------------------------------------- constants
# Pinned to the CDK CLI version the project was built and deployed with
# (matches aws-cdk-lib >=2.251,<3). A floating "aws-cdk@2" can outrun the library.
CDK_CLI_VERSION = "2.1145.0"
DEFAULT_REGION = "us-east-1"
# The Runtime IAM policy and BEDROCK_MODEL_ID use this US cross-region inference
# profile, so the deploy region must be a US region (us-east-1, us-east-2, us-west-2).
MODEL_PROFILE_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
MIN_NODE = (20, 9)  # Next.js 16 requires Node >= 20.9
MIN_PYTHON = (3, 10)

# Stack groups, in deploy order. Names must match infra-cdk/app.py (a unit test checks).
BACKEND_STACKS = [
    "MahaloMemoryIdentityStack",
    "MahaloGatewayStack",
    "MahaloMockJiraStack",
    "MahaloMockConfluenceStack",
    "MahaloMockGithubStack",
    "MahaloMockServicenowStack",
    "MahaloDashboardStack",
]
RUNTIME_API_STACKS = ["MahaloRuntimeStack", "MahaloApiStack"]
KEEPWARM_STACKS = ["MahaloKeepWarmStack"]
FRONTEND_STACKS = ["MahaloFrontendStack"]
ALL_STACKS = BACKEND_STACKS + RUNTIME_API_STACKS + KEEPWARM_STACKS + FRONTEND_STACKS

# Demo persona logins (hard-coded demo credentials that already ship in the repo).
PERSONA_LOGINS = [("pm", "pm123"), ("dev", "dev123"), ("exec", "exec123")]


class DeployError(Exception):
    """A user-facing failure: printed without a traceback, exit code 1."""


# --------------------------------------------------------------------------- context
class Ctx:
    """Target account selection + behaviour flags shared by every command."""

    def __init__(self, profile=None, region=None, dry_run=False, yes=False, expect_account=None):
        self.profile = profile or os.environ.get("AWS_PROFILE")
        self.region = (
            region
            or os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
            or DEFAULT_REGION
        )
        self.dry_run = dry_run
        self.yes = yes
        self.expect_account = expect_account

    def env(self, extra=None):
        """Environment for child processes: region/profile pinned, nothing leaked."""
        env = os.environ.copy()
        env["AWS_REGION"] = self.region
        env["AWS_DEFAULT_REGION"] = self.region
        env["CDK_DEFAULT_REGION"] = self.region
        if self.profile:
            env["AWS_PROFILE"] = self.profile
        env["JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        if extra:
            env.update(extra)
        return env


# --------------------------------------------------------------------------- helpers
def venv_python() -> Path:
    sub = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    return INFRA / ".venv" / sub


def cdk_env(ctx: Ctx, extra=None) -> dict:
    """Env for cdk: the infra-cdk venv first on PATH so cdk.json's `python app.py` uses it."""
    env = ctx.env(extra)
    env["PATH"] = str(venv_python().parent) + os.pathsep + env.get("PATH", "")
    env["VIRTUAL_ENV"] = str(INFRA / ".venv")
    env.pop("PYTHONHOME", None)
    return env


def tool(name: str) -> str:
    """Resolve an executable (handles npx.cmd / npm.cmd on Windows)."""
    return shutil.which(name) or name


def quote(cmd) -> str:
    return subprocess.list2cmdline([str(c) for c in cmd]) if os.name == "nt" else shlex.join(
        [str(c) for c in cmd]
    )


def run(ctx: Ctx, cmd, *, cwd=None, env=None, capture=False, check=True, mutating=True, note=None):
    """Run a command. In --dry-run, mutating commands are printed, not executed.

    `note` documents environment flags that change what the command does (they are
    set in `env`, which a printed command line would otherwise hide).
    """
    cmd = [str(c) for c in cmd]
    if ctx.dry_run and mutating:
        where = f"   (cwd={cwd})" if cwd else ""
        extra = f"   [env: {note}]" if note else ""
        print(f"  [dry-run] {quote(cmd)}{where}{extra}")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    if not capture:
        print(f"  $ {quote(cmd)}" + (f"   [env: {note}]" if note else ""))
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=env if env is not None else ctx.env(),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=capture,
        )
    except FileNotFoundError as exc:
        if not check:  # probes (preflight) want a result, not an exception
            return subprocess.CompletedProcess(cmd, 127, "", f"command not found: {cmd[0]}")
        raise DeployError(f"command not found: {cmd[0]} ({exc})") from exc
    if check and proc.returncode != 0:
        tail = ""
        if capture:
            tail = "\n" + ((proc.stderr or proc.stdout or "").strip()[-1500:])
        raise DeployError(f"command failed (exit {proc.returncode}): {quote(cmd)}{tail}")
    return proc


def aws(ctx: Ctx, *args, check=True, mutating=False):
    """Run an AWS CLI command (read-only by default) and capture output."""
    return run(ctx, [tool("aws"), *args], capture=True, check=check, mutating=mutating)


def first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def parse_version(text):
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    if not m:
        return None
    return tuple(int(x) if x else 0 for x in m.groups())


def find_output(outputs, key):
    """Pick one OutputValue from a describe-stacks Outputs list."""
    for item in outputs or []:
        if item.get("OutputKey") == key:
            return item.get("OutputValue")
    return None


def stack_exists_status(ctx: Ctx, stack: str):
    """Return the CloudFormation StackStatus, or None if the stack does not exist."""
    proc = aws(
        ctx, "cloudformation", "describe-stacks", "--stack-name", stack,
        "--query", "Stacks[0].StackStatus", "--output", "text", check=False,
    )
    if proc.returncode == 0:
        return proc.stdout.strip()
    if "does not exist" in (proc.stderr or ""):
        return None
    raise DeployError(f"could not describe stack {stack}: {first_line(proc.stderr)}")


def stack_output(ctx: Ctx, stack: str, key: str, placeholder=None):
    """Read one CfnOutput from a deployed stack (placeholder returned in --dry-run)."""
    if ctx.dry_run and placeholder is not None:
        return placeholder
    proc = aws(
        ctx, "cloudformation", "describe-stacks", "--stack-name", stack,
        "--query", "Stacks[0].Outputs", "--output", "json", check=False,
    )
    if proc.returncode != 0:
        raise DeployError(
            f"stack {stack} not found or unreadable ({first_line(proc.stderr)}). "
            "Has the stage that creates it been deployed?"
        )
    value = find_output(json.loads(proc.stdout or "null"), key)
    if not value:
        raise DeployError(f"stack {stack} has no output {key!r}")
    return value


def caller_identity(ctx: Ctx) -> dict:
    if ctx.dry_run:
        return {"Account": "<account-id>", "Arn": "<principal-arn>"}
    proc = aws(ctx, "sts", "get-caller-identity", "--output", "json", check=False)
    if proc.returncode != 0:
        raise DeployError(
            "AWS credentials are not usable. Configure a profile first "
            "(aws configure --profile <name>  or  aws configure sso --profile <name>) "
            f"and pass --profile <name>.  Detail: {first_line(proc.stderr)}"
        )
    return json.loads(proc.stdout)


def confirm_target(ctx: Ctx, action: str, stacks=None) -> dict:
    """Show exactly where we are about to act and require an explicit yes."""
    ident = caller_identity(ctx)
    account = ident["Account"]
    if ctx.expect_account and not ctx.dry_run and account != ctx.expect_account:
        raise DeployError(
            f"refusing to continue: the credentials point at account {account}, "
            f"but --expect-account is {ctx.expect_account}."
        )
    print("-" * 70)
    print(f"  Action    : {action}")
    print(f"  Account   : {account}")
    print(f"  Principal : {ident['Arn']}")
    print(f"  Region    : {ctx.region}")
    print(f"  Profile   : {ctx.profile or '(default credential chain)'}")
    if stacks:
        print(f"  Stacks    : {', '.join(stacks)}")
    print("-" * 70)
    if ctx.yes or ctx.dry_run:
        return ident
    if not sys.stdin.isatty():
        raise DeployError(
            "non-interactive session: re-run with --yes once the account above has been "
            "confirmed (also pass --expect-account <id> as a guard)."
        )
    if input("Is this the correct AWS account? Type 'yes' to continue: ").strip().lower() != "yes":
        raise DeployError("aborted by user")
    return ident


def cdk_cmd(*args):
    # infra-cdk/cdk.json defaults giteaMode to "real" (the original author's account
    # has a Gitea server). A personal account has none, so every cdk call here forces
    # the mock GitHub tool. Without this override the GitHub Lambda would point at a
    # Gitea host and an SSM token that do not exist in your account.
    return [tool("npx"), "--yes", f"aws-cdk@{CDK_CLI_VERSION}", *args, "-c", "giteaMode=mock"]


def require_docker(ctx: Ctx):
    if ctx.dry_run:
        return
    proc = run(ctx, [tool("docker"), "info"], capture=True, check=False, mutating=False)
    if proc.returncode != 0:
        raise DeployError(
            "Docker is not running. Start Docker Desktop (Linux containers) and retry. "
            "Docker is needed to build the arm64 agent image and bundle the API Lambda."
        )


# --------------------------------------------------------------------------- stages
def ensure_setup(ctx: Ctx):
    py = venv_python()
    if py.exists() and not ctx.dry_run:
        return
    cmd_setup(ctx, argparse.Namespace())


def stage_backend(ctx: Ctx):
    print("\n== Stage 1/3: backend (mock systems, Gateway, Memory, dashboard table) ==")
    run(ctx, cdk_cmd("deploy", *BACKEND_STACKS, "--require-approval", "never"),
        cwd=INFRA, env=cdk_env(ctx))


def stage_runtime_api(ctx: Ctx, with_keepwarm: bool):
    print("\n== Stage 2/3: agent Runtime + thin API (needs Docker) ==")
    require_docker(ctx)
    stacks = RUNTIME_API_STACKS + (KEEPWARM_STACKS if with_keepwarm else [])
    run(ctx, cdk_cmd("deploy", *stacks, "--require-approval", "never"),
        cwd=INFRA, env=cdk_env(ctx, {"MAHALO_BUILD_IMAGE": "1"}), note="MAHALO_BUILD_IMAGE=1")


def stage_frontend(ctx: Ctx):
    print("\n== Stage 3/3: frontend (build with the API URL baked in, then upload) ==")
    api_url = stack_output(ctx, "MahaloApiStack", "RuntimeApiUrl",
                           placeholder="https://<runtime-api-url>/")
    print(f"  API URL baked into the site: {api_url}")
    build_env = ctx.env({
        "NEXT_PUBLIC_API_URL": api_url,
        "NEXT_PUBLIC_AWS_REGION": ctx.region,
        "NEXT_TELEMETRY_DISABLED": "1",
    })
    run(ctx, [tool("npm"), "ci"], cwd=FRONTEND, env=build_env)
    run(ctx, [tool("npm"), "run", "build"], cwd=FRONTEND, env=build_env,
        note="NEXT_PUBLIC_API_URL=<the API URL above>, NEXT_PUBLIC_AWS_REGION=" + ctx.region)
    if not ctx.dry_run and not (FRONTEND / "out" / "index.html").exists():
        raise DeployError("frontend build produced no frontend/out/index.html")
    run(ctx, cdk_cmd("deploy", *FRONTEND_STACKS, "--exclusively", "--require-approval", "never"),
        cwd=INFRA, env=cdk_env(ctx, {"MAHALO_BUILD_FRONTEND": "1"}), note="MAHALO_BUILD_FRONTEND=1")


# --------------------------------------------------------------------------- commands
def cmd_setup(ctx: Ctx, args):
    """Create infra-cdk/.venv and install the CDK app's Python dependencies."""
    print("== setup: Python virtualenv for the CDK app ==")
    if sys.version_info < MIN_PYTHON:
        raise DeployError(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required, found {platform.python_version()}")
    if not (INFRA / ".venv").exists() or ctx.dry_run:
        run(ctx, [sys.executable, "-m", "venv", str(INFRA / ".venv")])
    run(ctx, [str(venv_python()), "-m", "pip", "install", "--quiet", "--upgrade", "pip"])
    run(ctx, [str(venv_python()), "-m", "pip", "install", "--quiet", "-r",
              str(INFRA / "requirements.txt")])
    print("setup complete.")


class Report:
    """Collects PASS / WARN / FAIL lines for preflight."""

    def __init__(self):
        self.items = []

    def add(self, status, name, detail=""):
        self.items.append((status, name, detail))
        tail = f" - {detail}" if detail else ""
        print(f"[{status}] {name}{tail}")

    @property
    def failed(self):
        return any(s == "FAIL" for s, _, _ in self.items)

    def summary(self):
        counts = {k: sum(1 for s, _, _ in self.items if s == k) for k in ("PASS", "WARN", "FAIL")}
        print(f"\nPreflight: {counts['PASS']} passed, {counts['WARN']} warnings, {counts['FAIL']} failed.")


def classify_agentcore_probe(returncode: int, stderr: str):
    """Interpret the AgentCore control-plane probe. Returns (status, detail)."""
    s = (stderr or "").lower()
    if returncode == 0:
        return "PASS", "AgentCore control plane reachable in this region"
    if "invalid choice" in s or "unknown service" in s or "argument command" in s:
        return "WARN", "this AWS CLI is too old to probe AgentCore; upgrade AWS CLI v2"
    if "could not connect to the endpoint" in s:
        return "FAIL", "AgentCore is not available in this region; use a region where it is GA (try us-east-1)"
    if "accessdenied" in s or "not authorized" in s or "unauthorizedoperation" in s:
        return "WARN", "no permission to list AgentCore runtimes; deploy rights will decide"
    return "WARN", first_line(stderr) or f"probe exited {returncode}"


def cmd_preflight(ctx: Ctx, args):
    """Read-only checks. Exit code 1 if anything blocks the deployment."""
    r = Report()
    print(f"== preflight (region {ctx.region}, profile {ctx.profile or 'default chain'}) ==\n")

    # --- local toolchain ---
    py = sys.version_info
    r.add("PASS" if py >= MIN_PYTHON else "FAIL", "Python",
          f"{platform.python_version()} (need {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+)")

    node = run(ctx, [tool("node"), "--version"], capture=True, check=False, mutating=False)
    nv = parse_version(node.stdout) if node.returncode == 0 else None
    if nv is None:
        r.add("FAIL", "Node.js", "not found; install Node 20.9+ (22 or 24 LTS recommended)")
    else:
        r.add("PASS" if nv[:2] >= MIN_NODE else "FAIL", "Node.js",
              f"v{'.'.join(map(str, nv))} (need >= {MIN_NODE[0]}.{MIN_NODE[1]})")

    for exe in ("npm", "npx"):
        ok = shutil.which(exe) is not None
        r.add("PASS" if ok else "FAIL", exe, "found" if ok else "not found (comes with Node.js)")

    awsv = run(ctx, [tool("aws"), "--version"], capture=True, check=False, mutating=False)
    av = parse_version((awsv.stdout or "") + (awsv.stderr or "")) if awsv.returncode == 0 else None
    if av is None:
        r.add("FAIL", "AWS CLI", "not found; install AWS CLI v2")
        r.summary()
        return 1
    r.add("PASS" if av[0] >= 2 else "FAIL", "AWS CLI", f"v{'.'.join(map(str, av))} (need v2)")

    # --- credentials / account ---
    ident_proc = aws(ctx, "sts", "get-caller-identity", "--output", "json", check=False)
    if ident_proc.returncode != 0:
        r.add("FAIL", "AWS credentials",
              "not usable - run `aws configure --profile <name>` (or `aws configure sso`) and pass --profile. "
              + first_line(ident_proc.stderr))
        r.summary()
        return 1
    ident = json.loads(ident_proc.stdout)
    r.add("PASS", "AWS credentials", f"account {ident['Account']} as {ident['Arn']}")
    if ctx.expect_account:
        ok = ident["Account"] == ctx.expect_account
        r.add("PASS" if ok else "FAIL", "Expected account",
              "matches --expect-account" if ok else f"credentials are account {ident['Account']}, expected {ctx.expect_account}")

    # --- region ---
    if ctx.region.startswith("us-"):
        r.add("PASS", "Region", f"{ctx.region} (US region: required for the us. inference profile)")
    else:
        r.add("FAIL", "Region",
              f"{ctx.region} is not a US region; the stack uses the US cross-region inference profile. Use us-east-1.")

    # --- CDK bootstrap ---
    try:
        boot = stack_exists_status(ctx, "CDKToolkit")
    except DeployError as exc:
        r.add("WARN", "CDK bootstrap", f"could not check ({first_line(str(exc))})")
    else:
        if boot:
            r.add("PASS", "CDK bootstrap", f"CDKToolkit stack present ({boot})")
        else:
            r.add("WARN", "CDK bootstrap", "not bootstrapped yet - run `deploy.py bootstrap`")

    # --- stale CDK state from another account ---
    for stale in (INFRA / "cdk.context.json", INFRA / "cdk.out"):
        if stale.exists():
            r.add("WARN", "Stale CDK state",
                  f"{stale.relative_to(REPO)} exists; it may hold another account's cached lookups - delete it before deploying")

    # --- Docker ---
    if not args.skip_docker:
        dv = run(ctx, [tool("docker"), "info"], capture=True, check=False, mutating=False)
        if dv.returncode != 0:
            r.add("FAIL", "Docker", "not running or not installed; start Docker Desktop (Linux containers)")
        else:
            r.add("PASS", "Docker", "daemon reachable")
            machine = platform.machine().lower()
            if machine in ("arm64", "aarch64"):
                r.add("PASS", "arm64 images", "host is arm64: native builds")
            else:
                emu = run(ctx, [tool("docker"), "run", "--rm", "--platform", "linux/arm64",
                                "public.ecr.aws/docker/library/busybox:latest", "uname", "-m"],
                          capture=True, check=False, mutating=False)
                if emu.returncode == 0 and "aarch64" in emu.stdout:
                    r.add("PASS", "arm64 images", "x86 host can run linux/arm64 containers (emulation works)")
                else:
                    r.add("FAIL", "arm64 images",
                          "x86 host cannot run linux/arm64 containers. Docker Desktop: update it. Linux: "
                          "`docker run --privileged --rm tonistiigi/binfmt --install arm64`. "
                          + first_line(emu.stderr))

    # --- Bedrock model: a real 5-token call is the only reliable access test ---
    if args.skip_model_invoke:
        r.add("WARN", "Bedrock model", "skipped (--skip-model-invoke)")
    else:
        inv = aws(ctx, "bedrock-runtime", "converse", "--model-id", MODEL_PROFILE_ID,
                  "--messages", json.dumps([{"role": "user", "content": [{"text": "hi"}]}]),
                  "--inference-config", json.dumps({"maxTokens": 5}), "--output", "json", check=False)
        if inv.returncode == 0:
            r.add("PASS", "Bedrock model", "Claude Sonnet 4.5 invoke succeeded (access enabled)")
        else:
            r.add("FAIL", "Bedrock model",
                  "Claude Sonnet 4.5 is not invokable. Enable model access in the Bedrock console "
                  "(Anthropic may ask for a one-time use-case form), then retry. " + first_line(inv.stderr))

    # --- AgentCore availability ---
    probe = aws(ctx, "bedrock-agentcore-control", "list-agent-runtimes", "--max-results", "1",
                "--output", "json", check=False)
    status, detail = classify_agentcore_probe(probe.returncode, probe.stderr)
    r.add(status, "Bedrock AgentCore", detail)

    r.summary()
    if r.failed:
        print("Fix the FAIL items above, then re-run preflight. Do not deploy until it is clean.")
        return 1
    print("Preflight is clean enough to deploy.")
    return 0


def cmd_bootstrap(ctx: Ctx, args):
    """One-time CDK bootstrap of the target account/region (safe to re-run)."""
    ident = confirm_target(ctx, "CDK bootstrap")
    run(ctx, cdk_cmd("bootstrap", f"aws://{ident['Account']}/{ctx.region}"),
        cwd=INFRA, env=cdk_env(ctx))
    print("bootstrap complete.")


def cmd_deploy(ctx: Ctx, args):
    stage = args.stage
    stacks = []
    if stage in ("all", "backend"):
        stacks += BACKEND_STACKS
    if stage in ("all", "runtime-api"):
        stacks += RUNTIME_API_STACKS + (KEEPWARM_STACKS if args.with_keepwarm else [])
    if stage in ("all", "frontend"):
        stacks += FRONTEND_STACKS
    confirm_target(ctx, f"deploy (stage: {stage})", stacks)
    started = time.time()
    ensure_setup(ctx)
    if stage in ("all", "backend"):
        stage_backend(ctx)
    if stage in ("all", "runtime-api"):
        stage_runtime_api(ctx, args.with_keepwarm)
    if stage in ("all", "frontend"):
        stage_frontend(ctx)
    print(f"\ndeploy ({stage}) finished in {int(time.time() - started) // 60} min.")
    if stage in ("all", "frontend"):
        print("Next: python deploy.py outputs   then   python deploy.py verify")


def collect_outputs(ctx: Ctx) -> dict:
    result = {}
    for stack in ALL_STACKS:
        proc = aws(ctx, "cloudformation", "describe-stacks", "--stack-name", stack,
                   "--query", "Stacks[0].Outputs", "--output", "json", check=False)
        if proc.returncode == 0:
            result[stack] = {o["OutputKey"]: o["OutputValue"] for o in json.loads(proc.stdout or "[]") or []}
    return result


def cmd_outputs(ctx: Ctx, args):
    data = collect_outputs(ctx)
    if args.json:
        print(json.dumps(data, indent=2))
        return
    if not data:
        print("No MAHALO stacks found in this account/region yet.")
        return
    for stack, outs in data.items():
        print(f"\n{stack}")
        for k, v in outs.items():
            print(f"  {k} = {v}")
    fe = data.get("MahaloFrontendStack", {}).get("FrontendUrl")
    if fe:
        print(f"\nOpen the app: {fe}")
        print("Demo logins : " + ", ".join(f"{u} / {p}" for u, p in PERSONA_LOGINS))


def cmd_status(ctx: Ctx, args):
    print(f"MAHALO stacks in region {ctx.region}:")
    for stack in ALL_STACKS:
        status = stack_exists_status(ctx, stack)
        print(f"  {stack:<30} {status or 'not deployed'}")


def http(method, url, headers=None, body=None, timeout=60):
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except OSError as exc:  # URLError, timeouts, connection resets
        return 0, str(exc)


def cmd_verify(ctx: Ctx, args):
    """End-to-end smoke test of the deployed app over HTTPS."""
    fe = stack_output(ctx, "MahaloFrontendStack", "FrontendUrl")
    api = stack_output(ctx, "MahaloApiStack", "RuntimeApiUrl").rstrip("/")
    ok = True
    print("== verify ==")

    code = 0
    for attempt in range(1, 7):  # CloudFront can take a few minutes to propagate
        code, _ = http("GET", fe, timeout=30)
        if code == 200:
            break
        print(f"  frontend not ready yet (HTTP {code}); retry {attempt}/6 in 20s")
        time.sleep(20)
    print(f"[{'PASS' if code == 200 else 'FAIL'}] frontend {fe} -> HTTP {code}")
    ok &= code == 200

    persona = {"X-Mahalo-Persona": "pm"}
    code, body = http("GET", f"{api}/dashboard/widgets", headers=persona, timeout=60)
    good = code == 200 and '"widgets"' in body
    print(f"[{'PASS' if good else 'FAIL'}] dashboard widgets (DynamoDB seeded default) -> HTTP {code}")
    ok &= good

    print("  sending a real chat to the agent (first call can take about a minute)...")
    started = time.time()
    payload = json.dumps({"message": "status", "session_id": "verify-" + str(uuid.uuid4())}).encode()
    code, body = http("POST", f"{api}/chat", body=payload, timeout=300,
                      headers={"Content-Type": "application/json", **persona})
    secs = time.time() - started
    good = code == 200 and '"response"' in body
    print(f"[{'PASS' if good else 'FAIL'}] /chat via AgentCore Runtime -> HTTP {code} in {secs:.0f}s")
    if not good:
        print("  response: " + body[:400].replace("\n", " "))
    ok &= good

    print("\n" + ("All checks passed." if ok else "Some checks failed - see TROUBLESHOOTING.md."))
    if ok:
        print(f"Open {fe} and log in with: " + ", ".join(f"{u}/{p}" for u, p in PERSONA_LOGINS))
    return 0 if ok else 1


def cmd_destroy(ctx: Ctx, args):
    existing = [s for s in ALL_STACKS if stack_exists_status(ctx, s)] if not ctx.dry_run else ALL_STACKS
    if not existing:
        print("Nothing to destroy: no MAHALO stacks found.")
        return
    confirm_target(ctx, "DESTROY (deletes the app and its data)", existing)
    run(ctx, cdk_cmd("destroy", *existing, "--force"), cwd=INFRA, env=cdk_env(ctx))
    print("destroy complete. The CDKToolkit bootstrap stack and its small asset bucket/ECR repo remain "
          "(see RUNBOOK.md 'Teardown' to remove them).")


def cmd_budget(ctx: Ctx, args):
    """Create a daily cost budget that emails you at 80% and 100% of the limit."""
    ident = confirm_target(ctx, f"create AWS Budget '{args.name}' (${args.amount}/day)")
    budget = {
        "BudgetName": args.name,
        "BudgetLimit": {"Amount": str(args.amount), "Unit": "USD"},
        "TimeUnit": "DAILY",
        "BudgetType": "COST",
    }
    notifications = [
        {
            "Notification": {
                "NotificationType": "ACTUAL",
                "ComparisonOperator": "GREATER_THAN",
                "Threshold": pct,
                "ThresholdType": "PERCENTAGE",
            },
            "Subscribers": [{"SubscriptionType": "EMAIL", "Address": args.email}],
        }
        for pct in (80, 100)
    ]
    cmd = [tool("aws"), "budgets", "create-budget", "--account-id", ident["Account"],
           "--budget", json.dumps(budget), "--notifications-with-subscribers", json.dumps(notifications),
           "--region", "us-east-1"]
    proc = run(ctx, cmd, capture=True, check=False, mutating=True)
    if proc.returncode == 0:
        print("budget created.")
    else:
        print("Could not create the budget (billing access may need enabling for IAM users): "
              + first_line(proc.stderr))
        print("Create it in the console instead: Billing > Budgets > Create budget.")


def cmd_up(ctx: Ctx, args):
    """Convenience: preflight -> bootstrap -> deploy (all) -> verify."""
    pf = argparse.Namespace(skip_docker=False, skip_model_invoke=False)
    if cmd_preflight(ctx, pf) != 0:
        raise DeployError("preflight failed; fix the FAIL items first")
    # Confirm the target once for the whole run instead of once per step.
    confirm_target(ctx, "FULL deploy: bootstrap + all stacks + verify", ALL_STACKS)
    ctx.yes = True
    cmd_bootstrap(ctx, args)
    cmd_deploy(ctx, argparse.Namespace(stage="all", with_keepwarm=args.with_keepwarm))
    return cmd_verify(ctx, args)


# --------------------------------------------------------------------------- CLI
def add_common(parser, root: bool):
    """Global flags; accepted before OR after the sub-command."""
    d = (lambda v: v) if root else (lambda v: argparse.SUPPRESS)
    parser.add_argument("--profile", default=d(None), help="AWS CLI profile for YOUR account (default: AWS_PROFILE / default chain)")
    parser.add_argument("--region", default=d(None), help=f"AWS region (default {DEFAULT_REGION}); must be a US region")
    parser.add_argument("--expect-account", default=d(None), help="abort unless the credentials belong to this 12-digit account id")
    parser.add_argument("--yes", action="store_true", default=d(False), help="do not prompt (use only after confirming the account)")
    parser.add_argument("--dry-run", action="store_true", default=d(False), help="print mutating commands instead of running them")


def build_parser():
    p = argparse.ArgumentParser(
        prog="deploy.py",
        description="Deploy MAHALO to your own AWS account (mock-git version).",
    )
    add_common(p, root=True)
    sub = p.add_subparsers(dest="command", required=True, metavar="command")

    def new(name, help_):
        sp = sub.add_parser(name, help=help_, description=help_)
        add_common(sp, root=False)
        return sp

    new("setup", "create infra-cdk/.venv and install CDK dependencies").set_defaults(func=cmd_setup)

    sp = new("preflight", "read-only checks of tools, credentials, Docker, Bedrock and AgentCore")
    sp.add_argument("--skip-docker", action="store_true", help="skip Docker checks")
    sp.add_argument("--skip-model-invoke", action="store_true", help="skip the 5-token Bedrock test call")
    sp.set_defaults(func=cmd_preflight)

    new("bootstrap", "one-time CDK bootstrap of the account/region").set_defaults(func=cmd_bootstrap)

    sp = new("deploy", "deploy the stacks (default: everything)")
    sp.add_argument("--stage", choices=["all", "backend", "runtime-api", "frontend"], default="all")
    sp.add_argument("--with-keepwarm", action="store_true",
                    help="also deploy the Runtime keep-warm ping (small recurring cost; off by default)")
    sp.set_defaults(func=cmd_deploy)

    sp = new("outputs", "print the URLs and IDs of the deployed stacks")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_outputs)

    new("status", "show the CloudFormation status of every MAHALO stack").set_defaults(func=cmd_status)
    new("verify", "smoke-test the deployed app (frontend, dashboard API, agent chat)").set_defaults(func=cmd_verify)
    new("destroy", "delete all MAHALO stacks").set_defaults(func=cmd_destroy)

    sp = new("budget", "create a daily AWS Budget with email alerts")
    sp.add_argument("--email", required=True, help="address that receives alerts")
    sp.add_argument("--amount", type=float, default=20.0, help="daily limit in USD (default 20)")
    sp.add_argument("--name", default="mahalo-daily", help="budget name")
    sp.set_defaults(func=cmd_budget)

    sp = new("up", "preflight, bootstrap, deploy everything, then verify")
    sp.add_argument("--with-keepwarm", action="store_true")
    sp.set_defaults(func=cmd_up)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    ctx = Ctx(
        profile=getattr(args, "profile", None),
        region=getattr(args, "region", None),
        dry_run=getattr(args, "dry_run", False),
        yes=getattr(args, "yes", False),
        expect_account=getattr(args, "expect_account", None),
    )
    try:
        rc = args.func(ctx, args)
        return int(rc or 0)
    except DeployError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
