# Task 3 Design Review — Confirmation Pass (iteration 5)

**Design reviewed:** `docs/.agents/tasks/task3-design.md`
**Prior review:** `docs/.agents/tasks/task3-design-review.json` (iteration 4 —
`CHANGES_REQUESTED`: 1 HIGH, 2 MEDIUM, 3 NIT)
**Verdict:** APPROVED

## Scope

This is a confirmation pass. I read the amended design fresh and re-verified each
of the six prior findings against the mahalo-dock mock sources (read-only) at
`D:/<USER>/LavaCode/AI/mahalo-dock/mock-services/<svc>/`:

- `github/seed_data.py`
- `github/mock_backend.py`
- `github/main.py`
- `servicenow/main.py`
- `jira/main.py`

I did not reopen the four resolved OPEN DECISIONS and did not raise new
out-of-scope architecture concerns. A finding is raised only if a prior finding
was not correctly applied or there is a genuine correctness defect in the amended
text.

## Confirmation of the six prior findings

All six are correctly applied. Each line below states the design location and the
mock fact that makes the amended text correct.

1. **[prior HIGH] GitHub collections keyed by repo id (`repo-N`), not name.**
   APPLIED. Decision 2 "Table shape" now uses `repo-1` as the `sk` example and adds
   the paragraph "**GitHub `sk` is the seed repo *id* (`repo-N`), never the
   `name`.**" stating strict identity matches and **no name→id resolution** anywhere,
   with the name-based 404 replicated verbatim. The one remaining `payment-service`
   mention (design line 203) correctly labels it as the seed's *separate* `name`
   field, not as a key example. Verified against `github/seed_data.py`: `REPOS` carry
   `id="repo-1".."repo-5"` with a separate `name`; `BRANCHES`/`CONTRIBUTOR_STATS`
   are dicts keyed `repo-1`..`repo-5`; `PULL_REQUESTS`/`COMMITS` carry
   `repo_id="repo-N"`. And `github/mock_backend.py`: `get_repo` uses
   `r["id"]==repo_id`, `list_branches`/`create_branch`/`create_pull`/`create_commit`
   use `repo_id not in BRANCHES`, `get_stats` uses `repo_id not in
   CONTRIBUTOR_STATS` — all identity matches, no name resolution.

2. **[prior MEDIUM] GitHub `create_repo` id normalization.** APPLIED. The
   "ID derivation and uppercasing on creates" block specifies github `create_repo`
   new id = `str(body.get("name") or "repo").lower().strip()` (lower+strip,
   contrasted with jira/confluence `.upper()`), states the 409 duplicate check and
   the `REPO`/`BRANCHSET` sk use this normalized id, `BRANCHSET` seeded with default
   `main`, and no `STATS` item. Verified against `mock_backend.create_repo`:
   `repo_id = str(repo.get("name") or "repo").lower().strip()`;
   `if any(r["id"] == repo_id for r in REPOS): raise BackendError(409, "Repository
   already exists")`; `BRANCHES.setdefault(repo_id, [{"name":"main","protected":True,
   "last_commit":"2026-08-29"}])`; no `CONTRIBUTOR_STATS` seeding.

3. **[prior MEDIUM] GitHub `POST /repos/{id}/branches` missing-name 422.** APPLIED.
   The GitHub inventory row lists `422 missing name`; the input-validation bullet
   states missing/empty `name` → 422, pydantic-sourced, body
   `{"detail":"Field 'name' is required"}`; and the pinned per-route 422 list places
   this route among the pydantic-sourced simplified-shape routes (distinct from the
   github commit/pull 422s that keep verbatim strings). Verified against
   `github/main.py`: `create_branch` binds `request: CreateBranchRequest`, where
   `CreateBranchRequest(name: str, from_branch: str = "main")` — `name` is a required
   pydantic field, so an absent/empty `name` is rejected with 422 before the backend
   runs.

4. **[prior NIT] ServiceNow unknown-service 404 detail.** APPLIED. ServiceNow
   behavioral details pin unknown `affected_service` → 404
   `{"detail":"Unknown affected_service"}` (verbatim), noting it is not a
   "... not found" form. Verified against `servicenow/main.py` `create_incident`:
   `if not any(s["id"] == request.affected_service for s in SERVICES): raise
   HTTPException(status_code=404, detail="Unknown affected_service")`.

5. **[prior NIT] Auth value-comparison exactness.** APPLIED. The Auth section states
   the value comparison is exact (`header_value != expected` → 401, including
   `None`/absence) and that only the header *key* lookup is case-insensitive.
   Verified: all four mocks (`jira`, `servicenow`, `github`, `confluence`)
   `verify_token` use `if x_api_token != API_TOKEN` — an exact value comparison with
   no trim/case-fold.

6. **[prior NIT] Jira `/sprints/{project_id}` is a project key.** APPLIED. The Jira
   inventory row annotates `{project_id}` is a project key (e.g. `PAY`), not a sprint
   id, and returns all sprints for that project. Verified against `jira/main.py`
   `@app.get("/sprints/{project_id}")` → `list_sprints`: filters `s["project_id"] ==
   project_id`, enriches the active sprint with `completed_points`/`total_points`,
   returns `{"sprints": project_sprints}`.

## Spot-check of adjacent correctness (no defects found)

While confirming, I re-checked the amended text against the mocks in the areas the
findings touched; all are behavior-equivalent:

- Commit shape predicate: design `has_files = isinstance(body.get("files"), list) or
  bool(body.get("path"))` is truthiness-equivalent to the mock's
  `isinstance(request.get("files"), list) or request.get("path")`. `author_id`
  optional (default `mahalo-bot`) when true, required when false — matches.
- Validation order for `POST /incidents` and `POST /stories` (422 required-field
  check before the 404 existence check) matches the mock's pydantic-before-body
  ordering (`CreateIncidentRequest`/`CreateStoryRequest` are pydantic models).
- ID generation: servicenow `INC-{max(2000, existing max)+1}` matches
  `create_incident`; github commit id `c{count+1:03d}` and PR id `pr-{count+1}`
  (count-based) with PR `number` `max+1` (max-based) match `mock_backend`.
- github 409 duplicate repo compares the normalized id against existing `REPO` ids —
  matches `any(r["id"] == repo_id for r in REPOS)`.

## Findings

None. No finding was left unapplied and no new correctness defect was found in the
amended text.

## Verified Assumptions

- GitHub seed `REPOS` use `id="repo-1".."repo-5"` with a separate `name`
  (`payment-service`, …); `BRANCHES`/`CONTRIBUTOR_STATS` are dicts keyed by `repo-N`;
  `PULL_REQUESTS`/`COMMITS` carry `repo_id="repo-N"`. (`github/seed_data.py`)
- `mock_backend.create_repo` normalizes id via `str(repo.get("name") or
  "repo").lower().strip()`, 409s on `any(r["id"]==repo_id)`, seeds a `main` branch
  via `BRANCHES.setdefault(...)`, and does not seed contributor stats.
  (`github/mock_backend.py`)
- All github repo existence checks are strict identity matches with no name→id
  resolution. (`github/mock_backend.py`)
- `github/main.py` `create_branch` binds the pydantic `CreateBranchRequest` with a
  required `name`, so a missing name yields a pre-body 422.
- `servicenow/main.py` `create_incident` raises 404 `{"detail":"Unknown
  affected_service"}` verbatim for an unknown service; `CreateIncidentRequest` is
  pydantic (422 for missing required fields before the body).
- All four mocks' `verify_token` use `x_api_token != API_TOKEN` (exact value compare).
- `jira/main.py` `/sprints/{project_id}` filters by `project_id` (a project key) and
  returns `{"sprints": [...]}` with the active sprint velocity-enriched.

## Unverified / Wrong Assumptions

- None. Every finding whose correctness depends on mock behavior was verified against
  the cited source file; no design claim contradicted a mock source.

## Verdict rationale (mechanical)

HIGH findings: 0. MEDIUM findings: 0. Per the gate rule (`HIGH + MEDIUM > 0` →
`CHANGES_REQUESTED`; `== 0` → `APPROVED`), the verdict is **APPROVED**.
