"""Offline unit tests for deploy.py (no AWS access, no Docker, no network).

Run from the repo root with any Python 3.10+:

    python -m unittest discover -s docs/deploy-aws-personal/tests -v
"""

import contextlib
import io
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import deploy  # noqa: E402  (path set above)


def run_main(argv):
    """Run deploy.main(argv), returning (exit_code, stdout)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = deploy.main(argv)
    return rc, buf.getvalue()


class StackNames(unittest.TestCase):
    """The script's stack names must match infra-cdk/app.py (drift guard)."""

    def test_literal_stacks_exist_in_app_py(self):
        text = (deploy.INFRA / "app.py").read_text(encoding="utf-8")
        literal = [s for s in deploy.ALL_STACKS if not s.startswith("MahaloMock")]
        for name in literal:
            self.assertIn(f'"{name}"', text, f"{name} is not instantiated in infra-cdk/app.py")

    def test_mock_stacks_are_built_from_the_service_list(self):
        text = (deploy.INFRA / "app.py").read_text(encoding="utf-8")
        self.assertIn('f"MahaloMock{service.capitalize()}Stack"', text)
        for svc in ("jira", "confluence", "github", "servicenow"):
            self.assertIn(f'"{svc}"', text)
            self.assertIn(f"MahaloMock{svc.capitalize()}Stack", deploy.ALL_STACKS)

    def test_no_duplicates_and_expected_count(self):
        self.assertEqual(len(deploy.ALL_STACKS), len(set(deploy.ALL_STACKS)))
        # 13 app stacks minus Gitea and Builder (deliberately not part of this package)
        self.assertEqual(len(deploy.ALL_STACKS), 11)
        self.assertNotIn("MahaloGiteaStack", deploy.ALL_STACKS)
        self.assertNotIn("MahaloBuilderStack", deploy.ALL_STACKS)


class MockGitOverride(unittest.TestCase):
    """infra-cdk/cdk.json defaults giteaMode=real; the personal package must force mock."""

    def test_every_cdk_command_forces_mock_git(self):
        for args in (("deploy", "MahaloApiStack"), ("bootstrap", "aws://1/us-east-1"), ("destroy", "X", "--force")):
            cmd = deploy.cdk_cmd(*args)
            self.assertEqual(cmd[-2:], ["-c", "giteaMode=mock"], cmd)

    def test_cdk_json_default_is_real(self):
        import json
        ctx = json.loads((deploy.INFRA / "cdk.json").read_text(encoding="utf-8"))["context"]
        self.assertEqual(ctx.get("giteaMode"), "real")  # the reason the override above exists

    def test_dry_run_plans_show_the_override(self):
        def boom(*a, **k):
            raise AssertionError("subprocess.run called during --dry-run")

        with mock.patch.object(subprocess, "run", side_effect=boom):
            rc, out = run_main(["deploy", "--dry-run", "--stage", "all"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(out.count("giteaMode=mock"), 3)  # backend, runtime-api, frontend


class PureHelpers(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(deploy.parse_version("v24.13.0"), (24, 13, 0))
        self.assertEqual(deploy.parse_version("aws-cli/2.15.30 Python/3.11"), (2, 15, 30))
        self.assertEqual(deploy.parse_version("20.9"), (20, 9, 0))
        self.assertIsNone(deploy.parse_version("no version here"))
        self.assertIsNone(deploy.parse_version(None))

    def test_node_minimum_comparison(self):
        self.assertTrue(deploy.parse_version("v20.9.0")[:2] >= deploy.MIN_NODE)
        self.assertFalse(deploy.parse_version("v18.19.0")[:2] >= deploy.MIN_NODE)
        self.assertTrue(deploy.parse_version("v24.13.0")[:2] >= deploy.MIN_NODE)

    def test_find_output(self):
        outs = [{"OutputKey": "A", "OutputValue": "1"}, {"OutputKey": "RuntimeApiUrl", "OutputValue": "https://x/"}]
        self.assertEqual(deploy.find_output(outs, "RuntimeApiUrl"), "https://x/")
        self.assertIsNone(deploy.find_output(outs, "Missing"))
        self.assertIsNone(deploy.find_output(None, "A"))

    def test_classify_agentcore_probe(self):
        c = deploy.classify_agentcore_probe
        self.assertEqual(c(0, "")[0], "PASS")
        self.assertEqual(c(2, "aws: error: argument command: Invalid choice")[0], "WARN")
        self.assertEqual(c(255, "Could not connect to the endpoint URL: https://bedrock-agentcore...")[0], "FAIL")
        self.assertEqual(c(254, "An error occurred (AccessDeniedException) when calling")[0], "WARN")
        self.assertEqual(c(1, "something odd")[0], "WARN")

    def test_model_profile_is_us_scoped(self):
        self.assertTrue(deploy.MODEL_PROFILE_ID.startswith("us.anthropic.claude-sonnet-4-5"))


class ContextAndEnv(unittest.TestCase):
    def test_region_default_and_override(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(deploy.Ctx().region, "us-east-1")
            self.assertEqual(deploy.Ctx(region="us-west-2").region, "us-west-2")
        with mock.patch.dict(os.environ, {"AWS_REGION": "us-east-2"}, clear=True):
            self.assertEqual(deploy.Ctx().region, "us-east-2")

    def test_env_pins_region_and_profile(self):
        ctx = deploy.Ctx(profile="personal", region="us-west-2")
        env = ctx.env({"EXTRA": "1"})
        self.assertEqual(env["AWS_PROFILE"], "personal")
        self.assertEqual(env["AWS_REGION"], "us-west-2")
        self.assertEqual(env["AWS_DEFAULT_REGION"], "us-west-2")
        self.assertEqual(env["CDK_DEFAULT_REGION"], "us-west-2")
        self.assertEqual(env["EXTRA"], "1")

    def test_cdk_env_puts_venv_first(self):
        env = deploy.cdk_env(deploy.Ctx())
        first = env["PATH"].split(os.pathsep)[0]
        self.assertEqual(Path(first), deploy.venv_python().parent)
        self.assertIn(".venv", env["VIRTUAL_ENV"])


class RunHelper(unittest.TestCase):
    def test_missing_binary_is_a_result_when_check_false(self):
        ctx = deploy.Ctx()
        proc = deploy.run(ctx, ["definitely-not-a-real-binary-xyz"], capture=True, check=False, mutating=False)
        self.assertEqual(proc.returncode, 127)

    def test_missing_binary_raises_when_check_true(self):
        ctx = deploy.Ctx()
        with self.assertRaises(deploy.DeployError):
            deploy.run(ctx, ["definitely-not-a-real-binary-xyz"], capture=True, check=True, mutating=False)

    def test_failed_command_raises_with_tail(self):
        ctx = deploy.Ctx()
        with self.assertRaises(deploy.DeployError) as cm:
            deploy.run(ctx, [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"],
                       capture=True, mutating=False)
        self.assertIn("exit 3", str(cm.exception))
        self.assertIn("boom", str(cm.exception))


class ArgParsing(unittest.TestCase):
    def test_global_flags_accepted_before_and_after_command(self):
        p = deploy.build_parser()
        a = p.parse_args(["--profile", "x", "deploy", "--region", "us-west-2", "--yes"])
        self.assertEqual((a.profile, a.region, a.yes, a.command), ("x", "us-west-2", True, "deploy"))
        b = p.parse_args(["deploy", "--profile", "y"])
        self.assertEqual(b.profile, "y")
        c = p.parse_args(["--profile", "z", "verify"])
        self.assertEqual(c.profile, "z")  # not clobbered by the sub-parser default

    def test_deploy_defaults(self):
        a = deploy.build_parser().parse_args(["deploy"])
        self.assertEqual(a.stage, "all")
        self.assertFalse(a.with_keepwarm)

    def test_budget_requires_email(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            deploy.build_parser().parse_args(["budget"])

    def test_command_required(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            deploy.build_parser().parse_args([])


class SafetyGuards(unittest.TestCase):
    def test_expect_account_mismatch_aborts(self):
        ctx = deploy.Ctx(yes=True, expect_account="111111111111")
        with mock.patch.object(deploy, "caller_identity", return_value={"Account": "222222222222", "Arn": "arn"}):
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(deploy.DeployError) as cm:
                deploy.confirm_target(ctx, "test")
        self.assertIn("refusing to continue", str(cm.exception))

    def test_expect_account_match_passes(self):
        ctx = deploy.Ctx(yes=True, expect_account="222222222222")
        with mock.patch.object(deploy, "caller_identity", return_value={"Account": "222222222222", "Arn": "arn"}):
            with contextlib.redirect_stdout(io.StringIO()):
                ident = deploy.confirm_target(ctx, "test")
        self.assertEqual(ident["Account"], "222222222222")

    def test_non_interactive_without_yes_aborts(self):
        ctx = deploy.Ctx()
        with mock.patch.object(deploy, "caller_identity", return_value={"Account": "1", "Arn": "a"}), \
                mock.patch.object(sys.stdin, "isatty", return_value=False):
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(deploy.DeployError) as cm:
                deploy.confirm_target(ctx, "test")
        self.assertIn("--yes", str(cm.exception))

    def test_interactive_no_aborts(self):
        ctx = deploy.Ctx()
        with mock.patch.object(deploy, "caller_identity", return_value={"Account": "1", "Arn": "a"}), \
                mock.patch.object(sys.stdin, "isatty", return_value=True), \
                mock.patch("builtins.input", return_value="no"):
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(deploy.DeployError):
                deploy.confirm_target(ctx, "test")


class DryRun(unittest.TestCase):
    """--dry-run must print the plan and execute NOTHING."""

    def _dry(self, argv):
        def boom(*a, **k):
            raise AssertionError(f"subprocess.run was called during --dry-run: {a}")

        with mock.patch.object(subprocess, "run", side_effect=boom):
            return run_main(argv)

    def test_full_deploy_plan(self):
        rc, out = self._dry(["deploy", "--dry-run", "--stage", "all"])
        self.assertEqual(rc, 0, out)
        for stack in deploy.BACKEND_STACKS + deploy.RUNTIME_API_STACKS + deploy.FRONTEND_STACKS:
            self.assertIn(stack, out)
        self.assertNotIn("MahaloKeepWarmStack", out)  # off by default (recurring cost)
        self.assertIn(f"aws-cdk@{deploy.CDK_CLI_VERSION}", out)
        self.assertIn("npm", out)
        self.assertIn("--require-approval never", out)
        self.assertNotIn("MahaloGiteaStack", out)
        self.assertNotIn("MahaloBuilderStack", out)

    def test_keepwarm_is_opt_in(self):
        rc, out = self._dry(["deploy", "--dry-run", "--stage", "runtime-api", "--with-keepwarm"])
        self.assertEqual(rc, 0, out)
        self.assertIn("MahaloKeepWarmStack", out)

    def test_single_stage_only_touches_its_stacks(self):
        rc, out = self._dry(["deploy", "--dry-run", "--stage", "backend"])
        self.assertEqual(rc, 0, out)
        self.assertIn("MahaloGatewayStack", out)
        self.assertNotIn("MahaloRuntimeStack", out)
        self.assertNotIn("MahaloFrontendStack", out)

    def test_bootstrap_plan_targets_account_and_region(self):
        rc, out = self._dry(["bootstrap", "--dry-run", "--region", "us-west-2"])
        self.assertEqual(rc, 0, out)
        self.assertRegex(out, r"bootstrap\s+aws://<account-id>/us-west-2")

    def test_destroy_plan_lists_all_stacks(self):
        rc, out = self._dry(["destroy", "--dry-run"])
        self.assertEqual(rc, 0, out)
        self.assertIn("destroy", out)
        self.assertIn("--force", out)
        for stack in deploy.ALL_STACKS:
            self.assertIn(stack, out)

    def test_budget_plan(self):
        rc, out = self._dry(["budget", "--dry-run", "--email", "me@example.com", "--amount", "15"])
        self.assertEqual(rc, 0, out)
        self.assertIn("create-budget", out)
        self.assertIn("DAILY", out)
        self.assertIn("me@example.com", out)


def _cp(rc=0, out="", err=""):
    return subprocess.CompletedProcess([], rc, out, err)


class PreflightFlow(unittest.TestCase):
    """Exercise cmd_preflight's control flow with canned command results."""

    def _fake_run(self, **over):
        """Return a fake deploy.run keyed on the command text; `over` overrides defaults."""
        defaults = {
            "node": _cp(0, "v24.13.0\n"),
            "aws --version": _cp(0, "aws-cli/2.31.0 Python/3.13 Windows/11\n"),
            "sts": _cp(0, '{"Account": "123456789012", "Arn": "arn:aws:iam::123456789012:user/me"}'),
            "CDKToolkit": _cp(0, "CREATE_COMPLETE\n"),
            "docker info": _cp(0, "ok"),
            "docker run": _cp(0, "aarch64\n"),
            "converse": _cp(0, "{}"),
            "list-agent-runtimes": _cp(0, "{}"),
        }
        defaults.update(over)

        def fake(ctx, cmd, **kw):
            text = " ".join(str(c) for c in cmd)
            for key, result in defaults.items():
                if key in text:
                    return result
            raise AssertionError(f"unexpected command in preflight: {text}")

        return fake

    def _run(self, argv, **over):
        buf = io.StringIO()
        with mock.patch.object(deploy, "run", side_effect=self._fake_run(**over)), \
                mock.patch.object(deploy.shutil, "which", return_value="/usr/bin/x"), \
                mock.patch.object(deploy, "tool", side_effect=lambda name: name), \
                mock.patch.object(deploy.platform, "machine", return_value="arm64"), \
                contextlib.redirect_stdout(buf):
            rc = deploy.main(["preflight", "--region", "us-east-1"] + argv)
        return rc, buf.getvalue()

    def test_all_good_exits_zero(self):
        rc, out = self._run([])
        self.assertEqual(rc, 0, out)
        self.assertNotIn("[FAIL]", out)
        self.assertIn("[PASS] Bedrock model", out)
        self.assertIn("clean enough to deploy", out)

    def test_no_credentials_fails_fast(self):
        rc, out = self._run([], sts=_cp(255, "", "Unable to locate credentials"))
        self.assertEqual(rc, 1)
        self.assertIn("[FAIL] AWS credentials", out)
        self.assertNotIn("Bedrock", out)  # stops before the dependent checks

    def test_model_not_invokable_fails(self):
        rc, out = self._run([], converse=_cp(254, "", "AccessDeniedException: not authorized"))
        self.assertEqual(rc, 1)
        self.assertIn("[FAIL] Bedrock model", out)

    def test_old_cli_is_only_a_warning_for_agentcore(self):
        rc, out = self._run([], **{"list-agent-runtimes": _cp(2, "", "aws: error: argument command: Invalid choice")})
        self.assertEqual(rc, 0, out)
        self.assertIn("[WARN] Bedrock AgentCore", out)

    def test_agentcore_missing_in_region_fails(self):
        rc, out = self._run([], **{"list-agent-runtimes": _cp(255, "", "Could not connect to the endpoint URL")})
        self.assertEqual(rc, 1)
        self.assertIn("[FAIL] Bedrock AgentCore", out)

    def test_unbootstrapped_is_a_warning_not_a_failure(self):
        rc, out = self._run([], CDKToolkit=_cp(255, "", "Stack with id CDKToolkit does not exist"))
        self.assertEqual(rc, 0, out)
        self.assertIn("[WARN] CDK bootstrap", out)

    def test_x86_host_without_emulation_fails(self):
        buf = io.StringIO()
        with mock.patch.object(deploy, "run", side_effect=self._fake_run(**{"docker run": _cp(125, "", "exec format error")})), \
                mock.patch.object(deploy.shutil, "which", return_value="/usr/bin/x"), \
                mock.patch.object(deploy, "tool", side_effect=lambda name: name), \
                mock.patch.object(deploy.platform, "machine", return_value="AMD64"), \
                contextlib.redirect_stdout(buf):
            rc = deploy.main(["preflight", "--region", "us-east-1"])
        self.assertEqual(rc, 1)
        self.assertIn("[FAIL] arm64 images", buf.getvalue())

    def test_non_us_region_fails(self):
        buf = io.StringIO()
        with mock.patch.object(deploy, "run", side_effect=self._fake_run()), \
                mock.patch.object(deploy.shutil, "which", return_value="/usr/bin/x"), \
                mock.patch.object(deploy, "tool", side_effect=lambda name: name), \
                mock.patch.object(deploy.platform, "machine", return_value="arm64"), \
                contextlib.redirect_stdout(buf):
            rc = deploy.main(["preflight", "--region", "eu-west-1"])
        self.assertEqual(rc, 1)
        self.assertIn("[FAIL] Region", buf.getvalue())

    def test_old_node_fails(self):
        rc, out = self._run([], node=_cp(0, "v18.19.0\n"))
        self.assertEqual(rc, 1)
        self.assertIn("[FAIL] Node.js", out)


class NoSensitiveValues(unittest.TestCase):
    """The package must not carry account ids, ARNs, emails or workstation paths."""

    def test_package_files_are_clean(self):
        pattern = re.compile(
            r"\b\d{12}\b|arn:aws:[a-z-]+:[a-z0-9-]*:\d{12}|[\w.+-]+@(?!example\.com)[\w-]+\.(?:org|com|net)"
            r"|[A-Za-z]:\\\\?[A-Za-z]|lavakumar\.baskaran|frb\.org",
        )
        package = HERE.parent
        # The tests use obviously fake 12-digit ids ("111111111111"); skip this file.
        for path in package.glob("*"):
            if path.is_file() and path.suffix in {".py", ".md", ".txt"}:
                text = path.read_text(encoding="utf-8")
                self.assertIsNone(pattern.search(text), f"sensitive-looking value in {path.name}")


if __name__ == "__main__":
    unittest.main()
