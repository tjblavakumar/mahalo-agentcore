---
name: jira-roadmap
description: Proposed roadmap for ONE project's next two sprints from open Jira stories and open ServiceNow incidents, with a developer allocation suggestion. Usage - /JIRA_ROADMAP PAY
---

# Jira roadmap proposal

Propose a roadmap for the next two sprints of the single project named in the run
arguments. This skill only reads Jira and ServiceNow. It does not create or change
anything.

## How this skill runs

The sprint selection, every total and the developer allocation are computed by
code, not by the model. The code reads the data, works out the plan, and writes
every table and number. The numbers are computed by code and shown unchanged.
No part of the answer is written by the model.

If the data cannot be read, the answer is a fixed message that says nothing was
changed. No partial numbers are shown.

## What the code reads

1. `jira_get_sprint_info` for the project: the recorded velocity of every completed sprint, the active sprint and any planned sprint.
2. `jira_search_stories` for the project, with no other filter.
3. `jira_list_developers`: skills and `capacity_points` for the project. A missing value is shown as "not recorded".
4. `servicenow_list_incidents` for the project's service (PAY payment-service, CART cart-service, AUTH auth-service, PROD product-service, ORD order-service). Incidents that are open or investigating are used.
5. `servicenow_list_deployments` for the same service.

## What the code computes

- Capacity per proposed sprint: the mean of the recorded velocities of all completed sprints, rounded half up to a whole point. The velocities and the addition are shown. If no completed sprint has a velocity, capacity cannot be sized and only the open stories are listed.
- Open stories are those whose status is not done. Groups: Backlog (no sprint), Planned (a planned sprint), Carry-over (a completed sprint, not done), In flight (the active sprint). In-flight stories are listed as "in flight, excluded" and are not planned.
- Order: stories reached from an open or investigating incident first, by incident severity P1 to P4; then priority critical, high, medium, low; carry-over before the rest within a priority; then story id.
- Fill Sprint A, then Sprint B, one story at a time in that order. A story is taken only if the running total stays at or below the capacity. Anything left is "Not scheduled". A story without recorded points is "points not recorded".
- Incident links: an incident is linked to a story ONLY through the incident's linked_deployment and that deployment's linked_story. With no linked_deployment it shows "no recorded link". If the linked story is not in the project's Jira stories it shows "linked story <id> not found in Jira". A link is never made from similar words or titles.
- Developer allocation (Inference): developer capacity is per sprint, from the capacity recorded for this project. A story that already has an assignee keeps it, and the developer is flagged with "over by N" when the stories named for them in a sprint are above their capacity. A story with no assignee goes to the developer with the best skill match who still has capacity left in that sprint ("skill match" or "capacity only" is shown). A developer with no recorded capacity is never chosen. If nobody has capacity, the cell says "no developer has capacity". The total developer capacity is compared with the sprint capacity.
- Risks: open or investigating incidents that have no open Jira story (no link, linked story not found, or linked story already Done).

## What the answer shows

Capacity, Sprint A (proposed), Sprint B (proposed), Not scheduled, Developer load (Inference), Incidents and risks, and Data notes when a field was missing or unrecognised. The two sprints are PROPOSED by this skill from recorded velocity. They are not read from Jira. Each sprint heading, its Total row and its written addition come from the same computed number.

## Rules

- Work on the project in the run arguments only.
- Every number, id and status comes from the data. If something is not in the data it is shown as "not recorded". Nothing is invented.
- Developer allocation is an inference and is labelled "Inference".
- No code is pasted.
