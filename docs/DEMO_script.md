# Mahalo demo script: one SuperMart feature, end to end (30 minutes)

This script follows the slide deck `docs/Mahalo_SuperMart_Demo.pptx` slide by slide; the deck's speaker notes carry the same talk track. Rebuild the deck with `python docs/demo/build_deck.py` (needs python-pptx).

The story follows **one feature, SuperMart crypto payments (Jira story PAY-109)**, through the whole delivery lifecycle, with each stage carried by the person who owns it:

| # | Stage | Who | System of record |
|---|---|---|---|
| 1 | Business need | SuperMart | (the request) |
| 2 | Story and plan | Marcus Chen, Product Manager | Jira |
| 3 | Design review | Maya Chaya, Architect | Jira, Confluence |
| 4 | Build | Lava Dev, Developer | Git (real Gitea), Jira |
| 5 | Tests and security | CI/CD pipeline | CI/CD (seeded demo results) |
| 6 | Release and support | Ops | ServiceNow |
| 7 | Leadership view | David Kim, Executive | all of the above |

Each persona's live demo **opens with their "Since yesterday" briefing card**, so the audience sees the previous person's handoff arrive without a meeting.

- **Mahalo UI:** https://dw28e5je2s7b9.cloudfront.net
- **Gitea (proof of real writes):** https://d3ec76atxiij9a.cloudfront.net/ (`mahalo_admin`)
- **Logins:** see `DEMO-LOGINS.md`.

> All prompts are grounded in the seeded demo data. Answers are written by an LLM, so wording can vary a little. Two things are computed in code and are identical every run: the `/JIRA_ROADMAP` plan and the login briefing.

## Before the demo (10 minutes before)

1. **Refresh demo data:** sign in as any persona, open **Settings**, click **Refresh demo data**. This resets Jira, Confluence and ServiceNow to the seed and moves every date up to today, so the briefings and the roadmap match this script. It does not touch Gitea.
2. **Check Gitea is up:** `GET https://d3ec76atxiij9a.cloudfront.net/api/v1/version` must answer (the host can auto-stop on weekends).
3. **Warm up:** send one throwaway chat prompt a few minutes before you start (the first call after idle can take 40 to 60 s).
4. **Hard-refresh** the UI (Ctrl+Shift+R) once.

## Timing at a glance

| Part | Slides | Minutes |
|---|---|---|
| The business and the problem | 1 to 5 | 5.5 |
| How Mahalo connects everyone; the feature we'll follow | 6 to 7 | 2.5 |
| Live: Marcus, story and plan | 8 | 3.5 |
| Live: Maya, design review | 9 | 3.5 |
| Live: Lava, build | 10 | 4.5 |
| Live: CI/CD tests and security | 11 | 2 |
| Live: release and support | 12 | 1.5 |
| Live: David, leadership view | 13 | 2.5 |
| Trust, Skills, what was real | 14 to 16 | 2.75 |
| Questions | 17 | 1.75 |

---

## Part 1: the business and the problem (slides 1 to 5, 0:00 to 5:30)

**Slide 1, Title (0:30).** "Today I'm not starting with technology. I'll start with a company, SuperMart, and one feature it wants: crypto payments. We'll follow that one feature from the business need all the way to what leadership sees. Everything after the slides is live."

**Slide 2, Meet SuperMart (1:00).** Browse, cart, sign in, pay, track order: each step is a separate system with a separate team.

**Slide 3, Five teams (1:00).**

| Key | Team | Repository | What it does |
|---|---|---|---|
| PROD | Catalog | product-service | Products, search, inventory |
| CART | Shopping cart | cart-service | Coupons, shipping, checkout |
| AUTH | Accounts | auth-service | Login, single sign-on, two-factor |
| PAY | Payments | payment-service | Cards, wallets, refunds, fraud checks |
| ORD | Orders | order-service | Fulfilment, tracking, returns |

Crypto payments belongs to PAY and payment-service. Every team uses the same five systems: Jira, Confluence, git, the CI/CD pipeline and ServiceNow.

**Slide 4, Challenges infographic (1:30).** Every handoff is a meeting, a spreadsheet or a copy-paste. Nobody is doing anything wrong; the tools just don't talk.

**Slide 5, Why it hurts (1:30).** Four quotes, in the order the feature moves:
- **Marcus Chen, PM:** "To plan a sprint I copy Jira and ServiceNow into a spreadsheet and guess who still has capacity."
- **Maya Chaya, Architect:** "I usually see a design after it ships, when it turns up in an incident."
- **Lava Dev, Developer:** "Half my morning is tab-switching: find my stories, check reviews, check the pipeline, update Jira."
- **David Kim, Executive:** "Before every release I ask where a feature is and who's at risk. It takes three meetings."

## Part 2: connected, and the feature we'll follow (slides 6 to 7, 5:30 to 8:00)

**Slide 6, Connected infographic (1:30).** One screen, one login, the same five systems behind it. Nothing is replaced. One screen works for four people because Mahalo knows who you are: each gets their own briefing, dashboard and suggestions.

**Slide 7, One feature, end to end (1:00).** Walk the seven stages. PAY-109, Cryptocurrency payment option: 13 points, PAY team, assigned to Lava. "Watch for the handoffs: each step shows up for the next person without an email."

---

## Part 3: live demo

### Stage 1-2. Marcus: the need becomes a plan (slide 8, 8:00 to 11:30)
**Sign in as Marcus Chen (Product Manager).**

0. **Briefing card** at the top of the chat. Read two lines, for example the P1 incidents and "PAY-109 assigned to Lava Dev". It's ranked in code from all five systems, so it's instant and the same every time.
1. **"Give me a status summary across all my projects — sprint progress, open PRs, and incidents."**
2. **"What's the status of PAY-109? Show its acceptance criteria."** Expect: To Do, 13 points, Lava Dev; BTC and ETH, QR code flow, automatic conversion to USD, 15-minute payment window.
3. Open **MahaloJira** (Connections, then "Open MahaloJira"): Current Sprint board and Backlog tab.
4. **`/JIRA_ROADMAP PAY`**:
   - Capacity 30 points per sprint.
   - Sprint A: 29 of 30 (PAY-110, PAY-098, PAY-099). Sprint B: 26 of 30.
   - PAY-109 is "not scheduled: exceeds remaining capacity": crypto payments competes with fraud detection (PAY-110) for capacity. That's a real planning conversation.
   - Overloaded people: dev-6 16 points over in Sprint A, dev-5 2 over in Sprint B.
   - Totals are computed in code: identical on every run.

Close: "Marcus's spreadsheet afternoon, in a few minutes. Now the story goes to the architect."

### Stage 3. Maya: design review before any code (slide 9, 11:30 to 15:00)
**Sign in as Maya Chaya (Architect).**

0. **Briefing card:** failed or rolled-back deploys, the SAML SSO design page updated, P1 incidents, review comments. It's about technical health, not sprint progress. Open the **Dashboard** briefly: change failure rate, security findings, incidents with and without a linked deployment, open PRs by service.
1. **"Review the design for PAY-109: risks, dependencies and what's missing."** An architecture review across services.
2. **"Draft an architecture decision record for adding crypto payments."** A **Download** button appears on the document. Click it: a real `.md` file.
3. **"Add a design-review comment to PAY-109 saying: Design review: use a provider abstraction and pin the crypto-signing library version."** An approval card appears. **Approve.**

Say: "Maya can comment on stories. If she asks Mahalo to commit code, it refuses: only developers commit."

### Stage 4. Lava: picks it up and ships the code (slide 10, 15:00 to 19:30)
**Sign in as Lava Dev (Developer).**

0. **Briefing card:** "PAY-109 assigned to you", and **Maya's design-review comment from two minutes ago**: the architect-to-developer handoff with no meeting. (The briefing caches for up to a minute; if her comment isn't there yet, refresh once.)
1. **Settings:** set the code-review model to **Nova Lite**. "Code is written by one model and reviewed by a different one."
2. **"What's assigned to me right now?"** PAY-109 and PAY-110 are among his stories.
3. **"Write the code for PAY-109, the cryptocurrency payment option, and commit it to the payment-service repo on a new branch."**
   - Stage progress: "Generating with Sonnet..." then "Reviewing with Nova Lite...".
   - Trust line: "Generated by Sonnet, reviewed by Nova Lite", with the findings.
   - Approval card for the branch and commit. **Approve.**
4. **"Move PAY-109 to in progress."** **Approve.**

Optional proof: open Gitea (`mahalo_admin`) and show the branch and commit.

### Stage 5. CI/CD: the pipeline tests it and catches a problem (slide 11, 19:30 to 21:30)
**Still as Lava.**

1. **"Did PAY-109 pass its tests and security scan?"** Expect **FAILED at the dependency scan**:
   - Unit 168 passed, integration 41 passed: 209 passed, 0 failed.
   - SAST passed with one medium finding (hard-coded test wallet key in a fixture).
   - Dependency scan: **one HIGH finding**, a known vulnerability in the crypto-signing library. The security gate blocks the release.

Say: "This is what Maya's review warned about: pin the crypto-signing library. CI/CD runs the tests and scans; Mahalo makes the results visible to everyone." Be honest: the answer is labelled "recorded demo data". These are seeded sample runs, not a live pipeline on the commit Lava just made.

### Stage 6. Release and support (slide 12, 21:30 to 23:00)
**Sign in as Maya again (or stay as Lava for the first question).**

1. **"Which services have the highest change failure rate?"** From ServiceNow deployments.
2. **"Which projects have failing pipelines or open security findings?"** A table across five projects; PAY-109, AUTH-306 and ORD-503 are blocked by high findings.
3. Optional: **"Which projects have open incidents in ServiceNow right now?"**

Say: "Ops keeps working in ServiceNow, as today. Mahalo doesn't deploy anything; it links each release and incident back to the story and the code."

### Stage 7. David: one question (slide 13, 23:00 to 25:30)
**Sign in as David Kim (Executive).**

0. **Briefing card:** portfolio risk only. P1 incidents, failed releases.
1. **"Where is crypto payments? Give me story, code, review, tests, security, deployment and incidents."** One answer: story in progress, the new branch and commit, the design review, tests passed, security failed on a high dependency finding, not deployed, no incidents yet, and a recommendation.
2. **"Show story points completed per project this sprint as a bar chart."**
3. Optional: **"What's our delivery risk across all five projects this sprint?"**

Close: "David's three meetings, answered in one question."

---

## Part 4: trust, Skills, what was real (slides 14 to 16, 25:30 to 28:15)

**Slide 14, Built-in trust (1:00).** Role-based access (only developers commit; only the architect comments), human approval for every write, a second-model code review, numbers computed in code (plan and briefing), honest labels, nothing replaced.

**Slide 15, Skills (0:45).** A skill is a saved, repeatable task behind a slash command. Mahalo can draft a new skill as a file you download, edit and upload in the skill library. Ideas (not built): release readiness check, incident hand-off summary, sprint retro starter, security findings digest.

**Slide 16, What you saw, honestly (1:00).** Real: the assistant and models, logins, role checks, approvals, the briefing, and git (Lava's commit is real). Demo data: Jira, Confluence and ServiceNow are sample data; CI/CD results are seeded sample runs; SuperMart is fictional. Next step: one pilot team with their real Jira, ServiceNow and CI/CD, plus two or three skills.

## Part 5: questions (slide 17, 28:15 to 30:00)

Recap the four quotes and how each was answered.

---

## Cheat sheet: prompts in order

**Marcus Chen (PM)**
- (Read the briefing card)
- Give me a status summary across all my projects — sprint progress, open PRs, and incidents.
- What's the status of PAY-109? Show its acceptance criteria.
- (Open MahaloJira: Current Sprint, Backlog)
- /JIRA_ROADMAP PAY

**Maya Chaya (Architect)**
- (Read the briefing card; open the Dashboard)
- Review the design for PAY-109: risks, dependencies and what's missing.
- Draft an architecture decision record for adding crypto payments. Then **Download**.
- Add a design-review comment to PAY-109 saying: Design review: use a provider abstraction and pin the crypto-signing library version. Then **Approve**.

**Lava Dev (Developer)**
- (Read the briefing card: PAY-109 assigned, Maya's comment)
- (Settings: code-review model = Nova Lite)
- What's assigned to me right now?
- Write the code for PAY-109, the cryptocurrency payment option, and commit it to the payment-service repo on a new branch. Then **Approve**.
- Move PAY-109 to in progress. Then **Approve**.
- Did PAY-109 pass its tests and security scan?

**Release and support (Maya)**
- Which services have the highest change failure rate?
- Which projects have failing pipelines or open security findings?
- *(optional)* Which projects have open incidents in ServiceNow right now?

**David Kim (Executive)**
- (Read the briefing card)
- Where is crypto payments? Give me story, code, review, tests, security, deployment and incidents.
- Show story points completed per project this sprint as a bar chart.
- *(optional)* What's our delivery risk across all five projects this sprint?

---

## Live-demo safety tips

- **Refresh demo data first** (Settings). After a rehearsal, approved writes stay in Jira (Maya's comment, PAY-109 in progress, any new stories) and the roadmap and briefings drift. Gitea is not reset: branches from earlier rehearsals stay.
- **Don't want a real branch?** Reject the approval card instead. The stage progress, the review and the trust line still show; nothing lands in Gitea. Then "Where is crypto payments?" will say no code is recorded.
- **Maya's comment not in Lava's briefing?** The briefing caches for up to a minute. Refresh the page once. If it still isn't there, the comment wasn't approved.
- **If a vague request reaches the PM or Executive** ("commit a README"), the model may ask for a branch name before it hits the role block. A direct request ("Create branch X now") is refused immediately.
- **Don't demo test coverage or "which missing tests caused incidents".** The only test data is the seeded pipeline runs.
- **Optimistic progress text:** "Reviewing with..." is shown client-side between send and response, so it can appear a moment early. The final "generated by X, reviewed by Y" labels come from the response.
- **Single Gitea admin by design:** every git write is owned by `mahalo_admin`; the persona appears in the PR and commit titles.
