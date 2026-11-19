# Skills (upload, store, validate, run SKILL.md files from the chat) - Requirements

## Summary

The team already writes `SKILL.md` files for daily work: Jira reports,
researching production issues, roadmaps from incidents and priority. Today those
files live outside Mahalo and are run by hand. This feature lets a user upload a
skill file on the Chatbot screen, have the orchestrator agent read it and
**validate** whether the task can be done (or what is missing: a connection to
another application, an output Mahalo cannot produce), and, **only after the user
consents to the plan**, perform the task. Skill files are **stored** in a shared
library, so a user can later type `/` in the chat box, pick a skill, and run it
again and again.

Decisions already made by the product owner (not re-opened here):

1. Skills are **common to all personas** (`pm`, `dev`, `exec`). Nothing is hidden per persona.
2. **Markdown files only.** No scripts, folders or bundled resources. Naming
   convention `<SYSTEM>_<WHAT>_SKILL.md`, for example `JIRA_ROADMAP_SKILL.md`.
   The slash command is the filename minus `_SKILL.md` (`/JIRA_ROADMAP`). The
   picker description comes from the file's frontmatter `description`.
3. **Output is chat text only** (formatted markdown). No PDF, file download or email.
4. A run targets **one project at a time** (`PAY`, `CART`, `AUTH`, `PROD`,
   `ORD`). The project is passed after the command (`/JIRA_ROADMAP PAY`). If it
   is omitted the system asks for it. No all-projects-in-one-run design.
5. In the past-sprint report, **"pending" = carry-over** (stories of that sprint
   not finished) **plus the current status** of those stories.
6. The Jira **seed data is enriched** so the two example skills give realistic,
   non-thin results.
7. Two **example skills ship pre-loaded** from a `skills/` folder committed in
   the repo, in addition to user upload.
8. **Consent model.** The user consents to the *plan* produced by the check
   step before the run starts. That consent is **not** approval of writes: the
   existing human-in-the-loop (HITL) gate over the six write tools
   (`jira_create_story`, `jira_update_story`, `github_create_branch`,
   `github_commit_files`, `github_open_pull_request`,
   `servicenow_create_incident`) stays exactly as is, and every write still
   needs its own approval. Both example skills are read-only.

The two example skills:

- **`JIRA_SPRINT_REPORT`**: for one project, the most recent completed sprint:
  what was done (stories, points), what is pending (carry-over with current
  status), team velocity (that sprint's, the trend across completed sprints, and
  current sprint progress).
- **`JIRA_ROADMAP`**: for one project, a proposed roadmap for the next two
  sprints from open Jira stories and open/investigating ServiceNow incidents,
  ordered by priority and incident severity, sized by the project's recorded
  velocity, with a developer allocation suggestion labelled as an inference.

## Functional Requirements

### Skill library (storage and pre-load)

- FR-1. The system shall keep **one shared skill library**, readable and
  writable by every persona.
- FR-2. A skill is addressed by its **command name**: the filename minus
  `_SKILL.md` (example: `JIRA_ROADMAP_SKILL.md` -> `JIRA_ROADMAP`). The command
  name is unique in the library.
- FR-3. Skills uploaded by users shall be **stored durably** and survive reloads,
  new chat sessions, a Runtime restart, and the existing "refresh demo data"
  action.
- FR-4. Two **built-in skills** (`JIRA_SPRINT_REPORT`, `JIRA_ROADMAP`) shall be
  available from the first request after deployment with no upload, sourced from
  Markdown files in a `skills/` folder committed in the repository.
- FR-5. Built-in skills are **read-only**: they cannot be overwritten or deleted
  through the API or the UI. Uploading a file whose command name equals a
  built-in name is rejected with a message that says so.
- FR-6. A user may **overwrite** a previously uploaded skill of the same name
  only after an explicit confirmation, and may **delete** an uploaded skill.
- FR-7. The library shall hold at most **50 uploaded skills**, and each skill
  file shall be at most **16 KB (16,384 bytes) of UTF-8**.

### Upload and validation

- FR-8. The Chatbot screen shall offer an **Upload skill** action that accepts a
  single `.md` file.
- FR-9. A file is valid only if all of these hold (exact rules in the design):
  1. the filename matches `<SYSTEM>_<WHAT>_SKILL.md` (uppercase letters,
     digits, underscores; at least two name parts before `_SKILL`);
  2. the file starts with YAML-style frontmatter between `---` lines;
  3. frontmatter has `name` and `description`; `name` is 1-64 chars, lowercase
     letters/digits/hyphens, not starting or ending with a hyphen, no
     consecutive hyphens (Agent Skills format), and equals the command name
     lowercased with `_` replaced by `-`; `description` is 1-1024 chars;
  4. the body after the frontmatter is not empty;
  5. size is within the cap and the text has no control characters other than
     tab, CR and LF.
- FR-10. Validation shall run in the **browser** for fast feedback and again on
  the **server**, which is the trust boundary. The two shall produce the same
  accept/reject decision for the same file.
- FR-11. A rejected upload shall show every violated rule in plain language and
  store nothing.
- FR-12. Frontmatter keys other than `name`, `description`, `license`,
  `compatibility` shall be accepted but **ignored**, and the upload result shall
  list them as warnings (in particular `allowed-tools`: a skill cannot grant
  tools).
- FR-13. Stored skill text shall only ever be **rendered as plain
  text** (the "View skill" view and the upload preview), never as HTML and never
  as Markdown, so a stored skill cannot load a remote image or show a clickable
  link. Skill *output* in chat uses the existing chat renderer.

### The "/" picker

- FR-14. Typing `/` as the first character of the chat input shall open a list
  of skills, filtered as the user types, showing the command name and the
  frontmatter description.
- FR-15. The list shall be operable by keyboard (arrows, Enter/Tab to select,
  Escape to close) and by mouse, and shall meet the accessibility criteria below.
- FR-16. After the command the user may type one **project argument**
  (`/JIRA_ROADMAP PAY`). The input shall validate it against the five project
  ids before sending and block the send with an inline message when it is
  invalid, or when the command name is not a known skill.
- FR-17. The message list shall show the command and project the user chose
  (for example `/JIRA_ROADMAP PAY`), **not** the skill body.

### Check step (validate before running)

- FR-18. Selecting a skill (or uploading one) shall run a **check step** before
  any run. The check shall **not execute the skill**: it shall call no tools and
  change nothing.
- FR-19. The check shall compare the skill's steps with a **capability manifest
  generated from the real tool definitions** (the 27 Gateway tool descriptors in
  `tools-lambdas/common/tool_schemas.py`, with the six gated write tools marked)
  plus a short explicit list of things Mahalo cannot do (write Confluence, send
  email, browse the web, run scripts or code, produce PDF or other files,
  create or edit sprints, schedule recurring runs).
- FR-20. The check result shall be structured and contain: a plain-language
  summary; the understood steps; the systems and tools needed; whether writes
  are involved (and which write tools); **gaps**, each marked `blocked` or
  `workable` with a workaround for workable ones; required arguments (the
  project) and whether each was provided; an estimated number of tool calls and
  a "likely too long for one turn" flag; and an overall **verdict**:
  `can_do`, `can_do_with_changes` or `cannot`.
- FR-21. The verdict, the write flag and the too-long flag shall be **derived by
  code** from the structured findings and the manifest, not taken from the
  model's opinion. A tool the model names that is not in the manifest shall
  become a `blocked` gap.
- FR-22. The UI shall show the check as a **card** with the summary, steps,
  gaps, arguments and warnings, and two actions: **Run** and **Cancel**. Run is
  disabled when the verdict is `cannot`, or while a required argument is missing
  (the card then offers a project selector).
- FR-23. When writes are involved the card shall say, before consent, that each
  write will still ask for its own approval.

### Run step

- FR-24. A run starts only after the user presses **Run** on the card for that
  exact skill text. If the stored skill changed after the check, the run is
  refused and the user is asked to re-check.
- FR-25. The skill text shall reach the agent as the **user's task description**
  inside a clearly delimited **skill-mode block**. The skill text shall not be
  able to add tools, change system rules, bypass the HITL gate, or override the
  honesty rules.
- FR-26. A run shall be **bounded**: at most 20 tool calls and about 170 seconds
  of tool use. When a bound is hit the agent shall stop calling tools, finish
  with what it has, and the response shall say **plainly** that the run was cut
  short (the notice is added by code, not left to the model).
- FR-27. A run that proposes a write shall stop at the existing approval card,
  and approval shall use the existing approve flow unchanged.
- FR-28. The final answer shall appear in the chat as formatted markdown
  (headings, tables, short bullets, code blocks). Tables shall use the existing
  badge convention: P1-P4 and status words alone in a table cell.
- FR-29. The result shall show a short **run summary line**: skill, project,
  tool calls used of the budget, elapsed seconds, and whether a bound was hit.
- FR-30. While a run is in progress the chat shall show progress (what is
  running, elapsed time) instead of a frozen spinner.

### Example skills

- FR-31. `JIRA_SPRINT_REPORT` shall, for one project, report on the **most
  recent completed sprint** (latest end date among completed sprints): done
  stories and points; pending = carry-over not finished, each with current
  status; that sprint's recorded velocity next to the points computed from its
  done stories; the velocity trend across the project's completed sprints; and
  current sprint progress. It shall say plainly when data is missing and shall
  never invent numbers.
- FR-32. `JIRA_ROADMAP` shall, for one project, propose a roadmap for the **next
  two sprints**:
  - candidates: the project's open Jira stories (backlog, planned-sprint,
    carry-over from completed sprints) and open or investigating ServiceNow
    incidents on the project's service (`payment-service`/PAY,
    `cart-service`/CART, `auth-service`/AUTH, `product-service`/PROD,
    `order-service`/ORD);
  - an incident links to a story **only** through `linked_deployment` ->
    that deployment's `linked_story`; otherwise it says there is no recorded
    link, and if the linked story does not exist in Jira it says so;
  - capacity per sprint = the project's recorded velocity;
  - order by incident severity (P1 to P4) and story priority;
  - developer allocation from developer skills and per-project capacity plus
    current assignments, **labelled as an inference**;
  - the two future sprints are **proposed by the agent, not read from Jira**
    (only PAY has a planned sprint today) and the output shall say so.
- FR-33. Both skills shall follow the agent prompt rules 9 and 10 (label
  inferences; never state a root cause or gap as fact without a source; link
  incidents to stories only through explicit data; no invented metrics; no
  full-file code in replies), use **existing read tools only**, and produce clean
  markdown.

### Seed data enrichment (Jira and ServiceNow mocks)

- FR-34. The Jira seed data shall be enriched **additively**: 3-4 completed
  sprints per project (PAY gets 4) with believable recorded velocities, stories
  in those sprints (including carry-over not finished), a few more open/backlog
  stories per project, and developer fields (`skills`, per-project
  `capacity_points`, optional `primary_service`).
- FR-35. No existing story's key, title, status or assignee shall change. The
  currently referenced items (PAY-105 in progress; PAY-109 and PAY-110 assigned
  to `dev-6`; CART-205; INC-2001, INC-2002, INC-2003; PAY-106, CART-204, AUTH-304,
  PROD-404, ORD-504 done) stay as they are.
- FR-36. For every completed sprint the recorded velocity shall equal the sum of
  the story points of its `done` stories, so the report can show the two numbers
  agreeing.
- FR-37. New sprints and stories shall work with the date shift
  (`tools-lambdas/common/seed_dates.py`), `Store.reset()` and
  `POST /admin/refresh-demo-data`, and shall keep the MahaloJira viewer (and its
  backlog rule that hides completed-sprint stories) working.
- FR-38. ServiceNow consistency shall be kept: deployments reference stories,
  incidents reference deployments, and `INC-2002` keeps **no** linked
  deployment. A small, explicit set of generated deployments shall be re-linked
  to real Jira stories so the incident -> deployment -> story chain resolves for
  the demo, while a few links stay unresolvable on purpose to exercise the
  "linked story not found in Jira" wording.
- FR-39. The agent shall be able to see the new developer fields and the
  sprint/priority of each story through its existing read tools, without adding
  or changing any tool argument.

### Compatibility and safety

- FR-40. `agent/approval.py`, `agent/hitl.py` and
  `agent/tools/github_write_tools.py` shall have **zero diff**.
- FR-41. The independent review sub-agent (`agent/review.py`, `tools=[]`, a
  different Bedrock model) and the multi-LLM configuration (table
  `mahalo-model-config`, `api/app/routers/model_config.py`) shall not be
  changed or disturbed. Skill runs shall not trigger a review stage on report
  text.
- FR-42. All new response fields are **additive and optional** so older clients
  keep working. Normal chat (no skill) behaves exactly as today.
- FR-43. Every field that crosses a layer (agent, API, frontend) shall use the
  **same key name**, and an **agent -> API contract test** shall exist for every
  new cross-layer field.

## Non-Functional Requirements

- NFR-1. **Turn time.** A chat turn is one blocking call (typically 40-60 s)
  through a Lambda Function URL with a 300 s limit. The check step shall
  complete in about 20 s or less (one model call, no tools, no Memory/Gateway
  start) and shall be bounded to about 45 s by a wall-clock deadline in the
  handler (with a capped output length, one attempt and a 40 s read timeout as
  additional limits; a read timeout alone is not a total-time bound for a streaming
  model), after which it returns an in-band `check_timeout` error. A skill run shall be sized to finish well inside 300 s (FR-26).
- NFR-2. **Offline-safety.** Importing any new agent or API module needs no AWS
  credentials or network. The DynamoDB table is built lazily.
- NFR-3. **Least privilege.** The API function gets read/write on the new skills
  table only. The Runtime role needs **no new permission** (it never reads the
  table). No new secret reaches the browser.
- NFR-4. **Security posture unchanged.** The thin API stays `AuthType=NONE`
  (accepted demo posture): **anyone who can reach the API can edit shared
  skills.** This is documented, not solved here.
- NFR-5. **No new tool.** The feature adds no Gateway tool and changes no tool
  argument, so the Gateway schema and its deploy are untouched. (A formatter
  change in `agent/tools/jira_tools.py` is output text only.)
- NFR-6. **Accessibility.** The picker uses the native textarea with only the ARIA
  attributes allowed on it (autocomplete, controls, activedescendant) and a
  listbox/option list, so it adds no `aria-allowed-role` violation; the check card and run status are announced to assistive technology;
  no information is conveyed by colour alone.
- NFR-7. **Static export.** The frontend remains a Next.js static export: no
  route handlers, server actions or dynamic routes are added.
- NFR-8. **Repository hygiene.** Committed files contain no AWS account id, ARN,
  token, password or absolute workstation path.

## Acceptance Criteria

Library and upload

1. Right after deployment, `GET /skills` lists `JIRA_SPRINT_REPORT` and
   `JIRA_ROADMAP` with `builtin: true`, each with the description from its file.
2. Uploading `JIRA_RELEASE_NOTES_SKILL.md` with valid frontmatter stores it;
   `GET /skills` then lists it with `builtin: false`; it is still listed after a
   page reload, a new session, and `POST /admin/refresh-demo-data`.
3. Uploading a built-in's filename is rejected with HTTP 409 and the message
   "built-in skills are read-only"; `DELETE /skills/JIRA_ROADMAP` returns 409.
4. Re-uploading an existing user skill without `overwrite: true` returns 409;
   with `overwrite: true` it replaces the text and updates `updated_at`.
5. These files are each rejected, with a specific message, on both the client
   and the server, and nothing is stored: `jira_roadmap.md` (bad filename);
   `JIRA_SKILL.md` (one name part); a file with no frontmatter; frontmatter
   without `description`; `name: Jira_Roadmap` (not lowercase-hyphen);
   `name: jira-other` in `JIRA_ROADMAP_SKILL.md` (name does not match
   filename); `name:` ending in a hyphen; an empty body; a 16,385-byte file; a
   file containing a NUL character; a body line starting with `[SYSTEM]`.
6. A shared vector file of valid and invalid skill files produces identical
   accept/reject results in the Python validator and the TypeScript validator.
7. Uploading a skill with `allowed-tools: Bash` stores it, ignores that key, and
   returns a warning naming it.
8. A stored skill whose text contains `<script>alert(1)</script>` is shown in
   the picker, the card and the preview as literal text; no element is created
   from it.
9. The 51st uploaded skill is rejected with HTTP 409 (`library_full`).

Picker

10. Typing `/` in an empty input opens a list with both built-ins, each showing
    command and description; typing `/JIRA_R` narrows it to `JIRA_ROADMAP`.
11. ArrowDown/ArrowUp move the highlight, Enter or Tab inserts
    `/JIRA_ROADMAP ` and closes the list, Escape closes it, and focus never
    leaves the text box. The text box keeps its native role (no `role`
    override) and exposes `aria-autocomplete="list"`, `aria-controls` and
    `aria-activedescendant` while the list is open; the list
    exposes `listbox`/`option`; a polite live region announces the match count.
12. After `/JIRA_ROADMAP ` a project suggestion list (PAY, CART, AUTH, PROD, ORD)
    appears. `/JIRA_ROADMAP XYZ` is blocked with "Project must be one of PAY,
    CART, AUTH, PROD, ORD" and nothing is sent. `/JIRA_ROADMAP pay` is accepted
    and normalised to `PAY`.
13. `/NOPE` is blocked with "No skill named /NOPE" and nothing is sent to the
    agent. Ordinary text that does not start with `/` is sent as chat exactly as
    today.
14. After sending `/JIRA_ROADMAP PAY` the message list shows `/JIRA_ROADMAP PAY`
    and not the skill body.

Check

15a. (Unit, deterministic.) With a fake draft whose steps use only read tools,
    `POST /skills/check` for `JIRA_ROADMAP` + `PAY` returns `verdict: can_do`,
    `writes_involved: false`, no gaps, `required_arguments` showing `project`
    provided, and tools limited to existing read tools.
15b. (Live.) For both built-in skills and all five projects the live check
    returns no `blocked` gap and `writes_involved: false`; a `can_do_with_changes`
    verdict with only `workable` gaps is acceptable and is logged as a
    check-prompt tuning item.
16. The check calls no tool: in the agent test the check agent is built with
    `tools=[]` and the test asserts the tool registry is empty.
17. A skill that says "publish the result to Confluence and attach a PDF"
    returns `verdict: cannot` with at least one `blocked` gap for the write to
    Confluence and one for PDF output, even if the model's own draft said
    `can_do` (the verdict is recomputed in code).
18. A skill that names a tool not in the manifest (for example `slack_post`)
    gets a `blocked` gap added by code.
19. A skill that includes "update the story status in Jira" returns
    `writes_involved: true` and `write_tools` containing `jira_update_story`; the
    card shows the "each write will still ask for approval" notice.
20. A skill estimated at more than 15 tool calls returns
    `likely_too_long: true` and the card shows the warning.
21. A `/JIRA_ROADMAP` with no project returns the `project` argument with
    `provided: false`; the card shows a selector and Run stays disabled until a
    project is chosen.
22. The check result for the same skill and project contains exactly the keys
    defined in the design, and the API model rejects an unknown key (a drifted
    key fails the contract test instead of being dropped).
23. The manifest contains every one of the 27 tool names in
    `tool_schemas.TOOLS`, and its write set equals `WRITE_TOOL_NAMES`.

Run

24. Pressing Cancel on the card runs nothing and shows "Cancelled. Nothing was
    run."
25. Pressing Run calls `POST /skills/run`; the API refuses (HTTP 409,
    `skill_changed`) if the stored text's SHA-256 differs from the one the card
    holds.
26. The agent receives the skill text only inside the skill-mode block; a unit
    test asserts the block's rules text, the random delimiter, and that a skill
    body containing the delimiter, or a line starting with `[SYSTEM]`, is
    refused before any model call.
27. A run that reaches 20 tool calls, or 170 s of tool use, cancels further tool
    calls, and the response ends with a code-added notice that the run was cut
    short; `skill_run.budget_exhausted` (or `deadline_exhausted`) is `true`.
28. Registering the budget hook does not change the six-write gate: a fake skill
    run that calls `jira_update_story` still returns `status:
    pending_approval` and `/chat/approve` still resumes it.
29. A skill run does not call the review sub-agent for a completed text answer
    (`_run_review` is not called; the `review` and `stages` keys are absent from
    the Runtime envelope and are `null` in the API response).
30. The run response carries `skill_run` with `name`, `project`,
    `tool_calls_used`, `tool_call_budget`, `budget_exhausted`,
    `deadline_exhausted`, `elapsed_seconds`; the UI shows the summary line.

Example skills and data

31. `JIRA_SPRINT_REPORT` for `PAY` (live check against enriched data) names
    Sprint 23 as the report sprint, lists PAY-101..PAY-104 as done (34 points),
    lists PAY-098 (In progress, 5) and PAY-099 (Todo, 3) as pending, shows
    recorded velocity 34 and the trend 26, 29, 31, 34, and shows current sprint
    progress 5 of 34 points. Every number can be traced to a tool result.
32. `JIRA_ROADMAP` for `PAY` shows capacity 30 points per sprint (mean of
    26, 29, 31, 34), proposes sprint A = PAY-110, PAY-098, PAY-099 and sprint
    B = PAY-092, PAY-094, PAY-085, PAY-091, PAY-095, states that these sprints
    are proposed and not in Jira, links INC-2012 to PAY-110 through DEP-1014,
    reports "no recorded link" for INC-2002, and reports "linked story PAY-601
    not found in Jira" for INC-2005. Allocation is labelled as an inference.
33. Both skills run for each of CART, AUTH, PROD and ORD without an error and
    without a number that is absent from the tool results.
34. Seed tests pass: unique story ids; every `sprint_id` resolves; recorded
    velocity equals done points for every completed sprint; every project has at
    least 3 completed sprints (PAY 4) and at least one carry-over story; the
    original S1 sprint is still the completed sprint with the latest end date;
    `PAY` story numbers do not exceed 110; the listed existing stories are
    unchanged; every re-linked deployment's story exists in Jira.
35. With `compute_shift_days` for several "today" values, every new sprint stays
    in order and keeps its weekday, and the completed sprints still end before
    the original S1 sprint.
36. After `POST /admin/refresh-demo-data` the enriched data is back to its seeded
    state and uploaded skills are untouched.
37. The existing Jira, ServiceNow, agent, API, infra and frontend test suites
    pass, including the Gateway schema parity test, the `PAY-111` create-story
    test and the MahaloJira viewer tests.

Safety

38. `git diff` shows no change to `agent/approval.py`, `agent/hitl.py`,
    `agent/tools/github_write_tools.py`, `agent/review.py`,
    `api/app/routers/model_config.py` and `tools-lambdas/common/tool_schemas.py`.
39. A repository scan of the committed files finds no AWS account id, ARN,
    token, password or absolute workstation path.

Added after design review

40. The key `skill_check` is used identically in the agent envelope, the API
    response and the frontend type; a contract test runs real handler output
    through the real router and asserts every key is present and non-null, and a
    second test feeds the router-built request body to the Runtime entry point.
41. A check that exceeds its time bound returns `status:"error"` with
    `error.type = "check_timeout"` within about 45 s. A unit test with a fake
    agent that sleeps past the deadline (patched to 0.1 s) shows the handler
    returns `check_timeout` promptly without waiting for the call; the check
    model is built with a capped `max_tokens`.
42. A model that keeps calling tools after the budget is exhausted is stopped
    after the second refusal round (a batch of parallel calls counts as one
    round); the response is exactly the code-written notice (not the Strands
    default "Turn ended early" text), and `skill_run.budget_exhausted` is `true`. The budget hook treats
    `jira___jira_update_story` (Gateway-prefixed) as a write and never counts or
    cancels it.
43. Typing `/JIRA_ROADMAP PAY` then Enter sends with project `PAY` (list closed);
    `/JIRA_ROADMAP` then Enter sends with no project; `/jira_roadmap pay` sends
    `JIRA_ROADMAP` with `PAY`.
44. A stored skill containing `![x](https://e/x.png)` renders no `<img>` and no
    `<a>` in "View skill" or in the upload preview.
45. The check returns no `missing_connection` gap for the system names
    "ServiceNow", "Jira Cloud" and "SNOW", lists a duplicate gap once, and sets
    `writes_involved` when the skill text names a write tool even if the model
    did not.
46. An infra test exercises the API bundling branch offline (monkeypatched
    `Code.from_asset`) and asserts the `skills/` copy command, the volume and
    `asset_hash_type`.
47. The check card handles failures: a check error shows its message and a
    **Check again** button; a run 409 `skill_changed` shows "This skill changed
    after the check. Check it again." with **Check again**; a 404 shows "This skill
    no longer exists." and removes the skill from the picker; a network or Lambda
    timeout on a run shows the read-only or write-skill message and re-enables the
    picker. One component test per case.
48. After a successful upload or delete in the library panel, the picker list
    shows the change without a page reload.
49. Importing `agent.skills` in a fresh interpreter with no network and no AWS
    credentials succeeds and builds the manifest.

## Out of Scope

- PDF, file download, email, Confluence publishing, or any output other than
  chat text.
- Scripts, folders, bundled resources or references inside a skill.
- Per-persona or per-team skill libraries, and hiding skills from a persona.
- Real authentication or authorization of skill editing (the API has none).
- Running one skill across all five projects in one turn.
- A background-job, streaming or queue architecture for long runs.
- Scheduling or recurring skill runs.
- Editing a skill in the UI (upload again with overwrite instead).
- Version history or rollback of skills.
- New Gateway tools, or new arguments on existing tools.
- Changing the HITL gate, the six write tools, the review sub-agent, or the
  multi-LLM configuration.
- Using the Strands `AgentSkills` plugin (the design explains why).

## Assumptions

- A1. "Skill header" in the request means the YAML frontmatter `description`.
- A2. The project argument is one word; a skill that needs no project is not
  supported in this slice (every run targets one of the five projects).
- A3. "Most recent completed sprint" means the completed sprint with the latest
  `end_date`, not the highest id.
- A4. The capacity of a proposed sprint is the mean of the project's recorded
  completed-sprint velocities, rounded to a whole point.
- A5. Stored skills are plain text; the persona header on the request is recorded
  as "claimed uploader" for display only, since the API does not verify it.
- A6. The two skills are written by the implementer from the drafts in the
  design; the product owner may revise the wording later without code changes.
