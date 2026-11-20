# Mahalo demo script: a day at SuperMart (30 minutes)

This script follows the slide deck `docs/Mahalo_SuperMart_Demo.pptx` slide by slide. The deck's speaker notes hold the same talk track. Rebuild the deck with `python docs/demo/build_deck.py` (needs python-pptx).

The story starts with the business, not the technology: a fictional online retailer, SuperMart, whose five product teams work in disconnected tools. Three people each describe their pain, then the live demo answers each pain directly.

- **Mahalo UI:** https://dw28e5je2s7b9.cloudfront.net
- **Gitea (proof of real writes):** https://d3ec76atxiij9a.cloudfront.net/ (`mahalo_admin`)
- **Personas:** David Kim (Executive), Marcus Chen (Project manager), Lava Dev (Developer)
- **Logins:** see `DEMO-LOGINS.md`.

> All prompts below are grounded in the seeded demo data, so they won't return "not found" on stage. Answers are written by an LLM, so the wording (and the chart type, when you don't name one) can vary a little. The `/JIRA_ROADMAP` plan is the exception: its numbers are calculated in code and are identical on every run.

## Timing at a glance

| Part | Slides | Minutes |
|---|---|---|
| The business and the problem | 1 to 5 | 7.5 |
| How Mahalo connects everyone | 6 | 2 |
| Live demo: Executive | 7 | 4 |
| Live demo: Project manager | 8 | 5 |
| Live demo: Developer | 9 | 5 |
| Live demo: Project manager again | 10 | 1.5 |
| Trust, Skills, real vs demo data | 11 to 13 | 3.5 |
| Questions | 14 | 1.5 |

---

## Part 1: the business and the problem (slides 1 to 5, 0:00 to 7:30)

**Slide 1, Title (0:30).** "Today I won't start with technology. I'll start with a company, SuperMart, and the people who build its online store. I'll show you their day now, then the same day with Mahalo. Everything after the slides is live."

**Slide 2, Meet SuperMart (1:30).** A customer browses products, adds them to a cart, signs in, pays, and tracks the order. Each step is a separate system owned by a separate team. That's normal for building software. The problem is what it does to anyone trying to see the whole picture.

**Slide 3, Five teams (1:00).** Explain the codes, because they come up in the demo:

| Key | Team | Repository | What it does |
|---|---|---|---|
| PROD | Catalog | product-service | Products, search, inventory |
| CART | Shopping cart | cart-service | Coupons, shipping, checkout |
| AUTH | Accounts | auth-service | Login, single sign-on, two-factor |
| PAY | Payments | payment-service | Cards, wallets, refunds, fraud checks |
| ORD | Orders | order-service | Fulfilment, tracking, returns |

Every team uses the same four tools: Jira for work, ServiceNow for incidents, Confluence for docs, git for code. Four tools times five teams is twenty places to look.

**Slide 4, Challenges infographic (3:00).** Walk the three people around the disconnected tools:
- **David Kim, Executive:** "Before every release I ask who's at risk. It takes three meetings, and the answer is already stale."
- **Marcus Chen, Project manager:** "To plan a sprint I copy Jira and ServiceNow into a spreadsheet and guess who still has capacity."
- **Lava Dev, Developer:** "Half my morning is tab-switching: find my stories, check incidents, wait for review, update Jira."

Nobody is doing anything wrong. The tools don't talk to each other, so people do the connecting by hand.

**Slide 5, Why it hurts (1:30).** The same gap, three ways: slow decisions for David, plans built on guesses for Marcus, lost build time for Lava. "Hold on to these three quotes. In the demo I'll answer each one."

## Part 2: how Mahalo connects everyone (slide 6, 7:30 to 9:30)

**Slide 6, Connected infographic (2:00).** One screen, one login, and behind it the same four tools. Nothing is replaced: Jira is still Jira and git is still git. Mahalo reads from all of them, so each person asks in plain English and gets an answer that already joins the data.

Why one screen works for three different people: Mahalo knows who you are. David gets portfolio answers and charts. Marcus gets his projects and plans. Lava gets his own stories and can write and commit code. Same tool, different view, shared facts.

---

## Part 3: live demo

### Executive: "who's at risk?" (slide 7, 9:30 to 13:30)
**Sign in as David Kim (Executive).**

1. **"Show story points completed per project this sprint as a bar chart."**
   Point out: a real chart from Jira data across all five projects, no spreadsheet.
2. **"What's our delivery risk across all five projects this sprint?"**
   Point out: sprint progress and open incidents combined, with the projects to watch called out. This is the "three meetings" question answered in one answer.
3. **"Which projects have open incidents in ServiceNow right now?"**
   Point out: a different system, same screen, no tab switch.
4. Optional if ahead of time: **"Show delivery risk by project as a pie chart."**
5. **Log out.**

Close: "David's question took seconds, and the answer is current, not last week's slide."

### Project manager: planning the sprint (slide 8, 13:30 to 18:30)
**Sign in as Marcus Chen (Project manager).**

1. **"Give me a status summary across all my projects — sprint progress, open PRs, and incidents."**
   Point out: Jira, git and ServiceNow in one answer.
2. **"Who is working on what in the payment project right now?"**
3. **"What's the status of PAY-105, and is there a pull request for it?"**
   *(PAY-105 is the Google Pay integration: in progress, with a real Gitea pull request.)* Point out: the story and its code are linked for him, without asking a developer.
4. Open **MahaloJira** (Connections, then "Open MahaloJira"). Show the **Current Sprint** board and the **Backlog** tab: the familiar Jira-style view of the same data.
5. **`/JIRA_ROADMAP PAY`** (the roadmap skill). Point out the plan:
   - PAY capacity is 30 points per sprint.
   - Sprint A: 29 of 30 points (PAY-110, PAY-098, PAY-099).
   - Sprint B: 26 of 30 points (PAY-092, PAY-094, PAY-085, PAY-091, PAY-095).
   - Overloaded people are flagged: dev-6 is 16 points over in Sprint A, dev-5 is 2 over in Sprint B.
   - The totals are calculated in code, not guessed by the AI. Run it twice and you get exactly the same answer, in a few seconds.
6. Optional: **"Show open stories by assignee in the payment project as a horizontal bar chart."**
7. **Log out.**

Close: "That was Marcus's spreadsheet afternoon, done in a few minutes."

For reference if asked: the current PAY sprint has 34 of 42 committed points done (81%). `/JIRA_SPRINT_REPORT PAY` shows it.

### Developer: story to commit on one page (slide 9, 18:30 to 23:30)
**Sign in as Lava Dev (Developer).**

1. **Settings:** choose **Nova Lite** as the code-review model.
   Say: "Code is generated by Sonnet and reviewed by a different model, Nova Lite, so the review is independent." *(The Security-review dropdown is disabled on purpose; it's the next slice.)*
2. **"What's assigned to me right now?"** Returns **PAY-109 (Cryptocurrency payment option)** and **PAY-110 (Fraud detection enhancement)**.
3. **"Write the code for PAY-109, the cryptocurrency payment option, and commit it to the payment-service repo on a new branch."**
   - Watch the stage progress: "Generating with Sonnet 4.5…" then "Reviewing with Nova Lite…".
   - See the trust line on the answer, "Generated by Sonnet 4.5, reviewed by Nova Lite", with the review findings.
   - An approval card appears for the commit. **Approve it.** Point out: nothing reaches git without a human yes.
4. **"Move PAY-109 to in progress."** Approval card, then **Approve**. Point out: the Jira update came from the same screen.
5. Optional: **"Show my assigned stories by status as a pie chart."**
6. **Log out.**

Then prove it's real: open Gitea (`mahalo_admin`) and show the branch and commit you just approved.

Close: "Find the story, write it, review it, commit it, update Jira. One page, no tab switch."

### Project manager again: the loop closes (slide 10, 23:30 to 25:00)
**Sign back in as Marcus Chen.**

1. **"What progress has been made on the payment project today?"** Picks up PAY-109, now in progress, with its new branch and commit.
2. **"Show me the latest pull requests and commits for payment-service."** Lava's work from two minutes ago is there.

Close: "The developer did the work, and the PM knows without anyone telling him."

---

## Part 4: trust, Skills, what was real (slides 11 to 13, 25:00 to 28:30)

**Slide 11, Built-in trust (1:30).** "What if it does something I didn't ask for?" Four answers: access follows your role (only a developer can commit code); every change waits for a human to approve; generated code gets a second review by a separate model; and numbers that matter, like the sprint plan, are calculated in code, so they repeat.

**Slide 12, Skills (1:00).** A skill is a saved, repeatable task behind a slash command. You saw `/JIRA_ROADMAP`. Ideas for SuperMart (not built yet): release readiness check, incident hand-off summary, sprint retro starter, new-starter onboarding guide.

**Slide 13, What you saw, honestly (1:00).** Real: the assistant and its models, the logins and approvals, and git (a real Gitea server; the commit Lava made is a real commit on a real branch). Demo data: Jira, ServiceNow and Confluence are realistic sample data, and SuperMart and its people are fictional. Connecting real tools swaps the data source; the screens, roles and approvals stay the same. Suggested next step: one pilot team, real Jira and ServiceNow, and two or three skills they choose.

## Part 5: questions (slide 14, 28:30 to 30:00)

Recap the three quotes and how each was answered, then take questions.

---

## Cheat sheet: prompts in order

**Executive (David Kim)**
- Show story points completed per project this sprint as a bar chart.
- What's our delivery risk across all five projects this sprint?
- Which projects have open incidents in ServiceNow right now?
- *(optional)* Show delivery risk by project as a pie chart.

**Project manager (Marcus Chen)**
- Give me a status summary across all my projects — sprint progress, open PRs, and incidents.
- Who is working on what in the payment project right now?
- What's the status of PAY-105, and is there a pull request for it?
- (Open MahaloJira: Current Sprint board, Backlog tab.)
- /JIRA_ROADMAP PAY
- *(optional)* Show open stories by assignee in the payment project as a horizontal bar chart.

**Developer (Lava Dev)**
- (Settings: choose Nova Lite as the code-review model.)
- What's assigned to me right now?
- Write the code for PAY-109, the cryptocurrency payment option, and commit it to the payment-service repo on a new branch. Then **Approve**.
- Move PAY-109 to in progress. Then **Approve**.
- *(optional)* Show my assigned stories by status as a pie chart.

**Project manager again (Marcus Chen)**
- What progress has been made on the payment project today?
- Show me the latest pull requests and commits for payment-service.

---

## Live-demo safety tips

- **Warm it up.** The first agent call after idle can take 40 to 60 s (cold start). Send one throwaway prompt a few minutes before you start.
- **Check Gitea is up.** It can auto-stop on weekends. It must answer at `GET https://d3ec76atxiij9a.cloudfront.net/api/v1/version`.
- **Hard-refresh** the Mahalo UI (Ctrl+Shift+R) once before starting.
- **Don't want to create a real branch?** Reject the approval card instead. The stage progress, the review and the trust line still show; nothing lands in Gitea.
- **Don't demo test coverage or "which missing tests caused incidents".** The demo data has no test records. If asked, say it's a natural next skill once real systems are connected.
- **PAY-109 and PAY-110** are Lava Dev's stories, so "what's assigned to me" and the build prompt line up. PAY-105 (Google Pay) is the in-progress story with a real PR.
- **If the developer flow already ran** in an earlier rehearsal, PAY-109 may already be "in progress". The flow still works; say "moving it again" or pick PAY-110.
- **Optimistic progress text:** "Reviewing with…" is shown client-side between send and response, so on a slow turn it can appear a moment early. The final "generated by X, reviewed by Y" labels come from the response.
- **Single Gitea admin by design:** every git write is owned by `mahalo_admin`; the author name in each PR or commit title is the persona. Mention it if anyone asks why the Gitea user is always the same.
