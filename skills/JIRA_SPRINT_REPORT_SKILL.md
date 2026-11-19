---
name: jira-sprint-report
description: Sprint report for ONE project's most recent completed sprint - what was done, what is pending (carry-over with current status) and team velocity. Usage - /JIRA_SPRINT_REPORT PAY
---

# Jira sprint report

Produce a sprint report for the single project named in the run arguments.
This skill only reads Jira. Do not propose any change.

## Rules

- Report on the project in the run arguments only. Do not query or mention other projects.
- Every number must come from a tool result. If a value is not in the data, write "not recorded". Never estimate or fill a gap.
- Say plainly when data is missing (for example fewer than two completed sprints, or no active sprint).
- The data holds no reasons for unfinished work. If you offer a reason, label it "Inference".
- Write story status words exactly as Done, In progress, In review or Todo, alone in their table cell.
- Do not paste code. Keep the report short and scannable.

## Steps

1. Call jira_get_sprint_info with the project id. Note every sprint: name, status, dates, recorded velocity, and completed/total points when shown.
2. The report sprint is the COMPLETED sprint with the latest end date (not the highest id). If no sprint is completed, say "No completed sprint is recorded for <project>" and stop.
3. Call jira_search_stories with the project id and no other filter. Keep the stories whose sprint id is the report sprint's id. Call jira_get_story only if a field you need is missing, at most 3 times.
4. Call jira_list_developers once and use it to turn assignee ids into names. An unassigned story shows "Unassigned".
5. From those stories compute: done = status done; pending = every other status (carry-over). Sum story points for each group. Committed = done + pending. Completion = done points / committed points, rounded to a whole percent.
6. Velocity: take the sprint's recorded velocity. Also show the sum of done story points. If they differ, show both and say which is which; do not reconcile them. For the trend, list the recorded velocities of ALL completed sprints in order of end date, with the change from the previous one and the average. If fewer than two completed sprints have a velocity, say the trend is not available.
7. Current sprint progress: use the active sprint from step 1 (completed points of total points). If the sprint info does not show the points, compute them from the stories whose sprint id is the active sprint. If there is no active sprint, say so.

## Output

Use these headings in this order.

## Sprint report: <PROJECT> - <sprint name> (<start> to <end>)
Source: Jira (jira_get_sprint_info, jira_search_stories, jira_list_developers)

### Summary
- Done: <n> stories, <points> points
- Pending (carry-over): <n> stories, <points> points
- Committed: <points> points; completion <percent>%
- Recorded velocity: <v> points (done points from stories: <points>)

### Done
A table: Story, Title, Points, Assignee.

### Pending
A table: Story, Title, Points, Assignee, Status (the current status). If none, write "Nothing pending."

### Velocity
A table: Sprint, Dates, Recorded velocity, Change. Then one line giving the average and the direction (up, down or flat) of the last change.

### Current sprint
One or two lines: sprint name, dates, points done of total.

### Data notes
Bullets for anything missing or inconsistent. If nothing, write "None."
