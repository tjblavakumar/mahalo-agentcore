"""Guard the sticky "real Gitea by default" setting in cdk.json.

A deploy of MahaloMockGithubStack without ``giteaMode=real`` silently reverts the
github tool Lambda to mock mode (agent git writes land in DynamoDB and never reach
Gitea). The default lives in cdk.json so every ``cdk`` CLI run picks it up; this test
fails loudly if someone removes or flips it by accident.
"""

import json
import pathlib

CDK_JSON = pathlib.Path(__file__).resolve().parent.parent / "cdk.json"


def test_gitea_mode_defaults_to_real():
    context = json.loads(CDK_JSON.read_text(encoding="utf-8"))["context"]
    assert context.get("giteaMode") == "real"
