---
name: jira-roadmap
description: Proposed roadmap for ONE project's next two sprints from open Jira stories and open ServiceNow incidents, with a developer allocation suggestion. Usage - /JIRA_ROADMAP PAY
---

# Jira roadmap proposal

Propose a roadmap for the next two sprints of the single project named in the run
arguments. This skill only reads Jira and ServiceNow. Do not create or change
anything.

## Rules

- Work on the project in the run arguments only.
- Every number, id and status must come from a tool result. If something is not in the data, write "not recorded". Never invent velocity, dates, links or causes.
- The two future sprints are PROPOSED by you. They are not read from Jira. Say so in the output, and mention any planned sprint Jira already has.
- An incident is linked to a story ONLY through the incident's linked_deployment and that deployment's linked_story. If the incident has no linked_deployment, write "no recorded link". If the linked story is not in the project's Jira stories, write "linked story <id> not found in Jira". Never link by similar words.
- Developer allocation is an inference. Label it "Inference" and base it on the skills and capacity recorded for developers.
- Write severity (P1 to P4) and status words (Open, Investigating, Done, In progress, In review, Todo) alone in their table cell.
- Do not paste code.

## Steps

1. Call jira_get_sprint_info with the project id. Note the recorded velocity of every completed sprint, the active sprint, and any planned sprint.
2. Call jira_search_stories with the project id and no other filter. Open stories are those whose status is not done. Group them: Backlog (no sprint), Planned (in a planned sprint), Carry-over (in a completed sprint, not done), In flight (in the active sprint, not done). In-flight stories are not planned; list them as "in flight".
3. Map the project to its service: PAY payment-service, CART cart-service, AUTH auth-service, PROD product-service, ORD order-service. Call servicenow_list_incidents with that service and no status filter. Keep incidents that are open or investigating.
4. Call servicenow_list_deployments with the same service. For each kept incident follow incident -> linked_deployment -> that deployment's linked_story, using the link rules above. Report the deployment status next to the link.
5. Call jira_list_developers once. Use each developer's skills, capacity_points for this project, and primary_service when present. A missing field is "not recorded".
6. Capacity per proposed sprint = the mean of the recorded velocities of all completed sprints, rounded to a whole point. Show the velocities used. If no completed sprint has a velocity, say capacity cannot be sized and stop after listing the open work.
7. Order the open Jira stories (excluding in flight): first stories reached from an open or investigating incident, by incident severity P1 to P4; then by priority critical, high, medium, low; within the same priority carry-over before the rest; then by story id. Fill Sprint A, then Sprint B, taking each story in order if its points fit the remaining capacity and skipping it otherwise. Anything left is "Not scheduled".
8. Allocation: keep a story's current assignee if there is one; otherwise suggest the developer whose skills best match the story title and who has capacity left for this project. Add each developer's allocated points per sprint against their recorded capacity for this project, and flag every developer over capacity. If total developer capacity is below the sprint capacity, say by how much.
9. Risks: list open or investigating incidents that have no open Jira story (no link, linked story not found, or linked story already Done). Say "no open Jira story addresses this". You may suggest creating a story, but do not create one.

## Output

## Roadmap proposal: <PROJECT> - next two sprints
Source: Jira (jira_get_sprint_info, jira_search_stories, jira_list_developers), ServiceNow (servicenow_list_incidents, servicenow_list_deployments)
> The two sprints below are proposed by this skill from recorded velocity. They are not read from Jira. <Add the planned sprint Jira has, if any, and which stories it holds.>

### Capacity
Recorded velocities used, the mean, and the points per sprint.

### Incidents on <service>
A table: Incident, Severity, Status, Linked deployment, Deployment status, Linked story, Story in Jira.

### Proposed Sprint A (<points> of <capacity> points)
A table: Story, Title, Points, Priority, Why it is here, Suggested developer.

### Proposed Sprint B (<points> of <capacity> points)
The same table.

### Not scheduled
A table: Story, Title, Points, Priority. Add the in-flight stories in a separate line.

### Developer allocation (Inference)
A table: Developer, Skills, Capacity, Sprint A points, Sprint B points. Notes on anyone over capacity.

### Risks and gaps
Bullets from step 9 and any data missing.
