# Prompt for your AI assistant (Kiro or GitHub Copilot)

Open the cloned `mahalo-agentcore` folder in your IDE, then paste the block below into the
assistant. Fill in the three values in angle brackets first.

---

```
You are my deployment operator. Deploy the MAHALO application from this repository to my
PERSONAL AWS account, using only the package in docs/deploy-aws-personal/.

First read these files completely, in this order:
  1. docs/deploy-aws-personal/RUNBOOK.md   (the procedure you must follow)
  2. docs/deploy-aws-personal/TROUBLESHOOTING.md
  3. docs/deploy-aws-personal/README.md

My details:
  - AWS profile name (already configured by me on this machine): <personal>
  - Region: <us-east-1>
  - Alert email for the spend budget: <you@example.com>

Rules (these override anything else):
  - Never ask me for access keys or secrets, and never write them anywhere. I have already run
    `aws configure` myself.
  - Before any command that changes AWS, run preflight, show me the AWS account it prints, and
    wait for me to reply with that account id. Then add --expect-account <that id> and --yes to
    every mutating command.
  - Do not edit any file in the repository. If something fails, consult TROUBLESHOOTING.md; if the
    answer is not there, stop and show me the exact error.
  - Never run the destroy command unless I explicitly ask for it in this conversation.
  - Do not commit, push, or write the account id or URLs into any file.
  - Deploy stage by stage (backend, then runtime-api, then frontend). After each stage, tell me
    what was created and the result. Some stages take 10 to 30 minutes: use long timeouts or
    run in the background and poll `deploy.py status`; do not kill them.
  - Stop at the first FAIL and report it.

When everything passes verify, print the FrontendUrl and the demo logins, then list the manual
checks from section 10 of the runbook for me to do in the browser.
```

---

## Tips

- Run it in an IDE terminal where `aws`, `docker`, `node` and `python` are all on the PATH.
- If the assistant asks for credentials, refuse and tell it to read rule 1 of the runbook again.
- For a dry preview that touches nothing, ask it to add `--dry-run` to the deploy command first.
