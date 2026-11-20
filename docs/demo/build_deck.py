"""Build docs/Mahalo_SuperMart_Demo.pptx, the 30-minute business-first demo deck.

Run from the repo root with any Python that has python-pptx installed:

    python docs/demo/build_deck.py

The two infographics (supermart-challenges.png, mahalo-connected.png) are
rendered from the SVGs next to this script. Speaker notes carry the talk track
and the exact live-demo prompts. Logins live in docs/DEMO-LOGINS.md, never here.
"""

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "Mahalo_SuperMart_Demo.pptx"

NAVY = RGBColor(0x1D, 0x2B, 0x36)
BLUE = RGBColor(0x2F, 0x8F, 0xD8)
GREEN = RGBColor(0x1F, 0x7A, 0x4D)
RED = RGBColor(0xB0, 0x3A, 0x2E)
GREY = RGBColor(0x5B, 0x67, 0x70)
LIGHT = RGBColor(0xF3, 0xF6, 0xF9)
LINE = RGBColor(0xD5, 0xDD, 0xE4)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

FONT = "Segoe UI"
W, H = Inches(13.333), Inches(7.5)

prs = Presentation()
prs.slide_width, prs.slide_height = W, H
BLANK = prs.slide_layouts[6]


# --------------------------------------------------------------------------- helpers
def _style(run, size, color=NAVY, bold=False, italic=False):
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.color.rgb = color
    run.font.bold = bold
    run.font.italic = italic


def text(slide, x, y, w, h, lines, size=18, color=NAVY, bold=False,
         align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, italic=False, spacing=6):
    """Add a text box. `lines` is a str or a list of str / (str, dict) tuples."""
    box = slide.shapes.add_textbox(x, y, w, h)
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.05)
    if isinstance(lines, str):
        lines = [lines]
    for i, item in enumerate(lines):
        line, opts = (item, {}) if isinstance(item, str) else item
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(spacing)
        r = p.add_run()
        r.text = line
        _style(r, opts.get("size", size), opts.get("color", color),
               opts.get("bold", bold), opts.get("italic", italic))
    return box


def bullets(slide, x, y, w, h, items, size=18, color=NAVY):
    return text(slide, x, y, w, h, [f"\u2022  {i}" if isinstance(i, str) else i for i in items],
                size=size, color=color, spacing=10)


def rect(slide, x, y, w, h, fill=LIGHT, line=None, shape=MSO_SHAPE.ROUNDED_RECTANGLE):
    s = slide.shapes.add_shape(shape, x, y, w, h)
    s.fill.solid()
    s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
        s.line.width = Pt(1)
    s.shadow.inherit = False
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = 0.08
    s.text_frame.text = ""
    return s


def header(slide, title, kicker=None):
    rect(slide, 0, 0, W, Inches(0.12), fill=BLUE, shape=MSO_SHAPE.RECTANGLE)
    if kicker:
        text(slide, Inches(0.6), Inches(0.35), Inches(12), Inches(0.4), kicker.upper(),
             size=12, color=BLUE, bold=True)
    text(slide, Inches(0.6), Inches(0.65), Inches(12.1), Inches(0.9), title, size=32, bold=True)


def footer(slide, n):
    text(slide, Inches(0.6), Inches(7.0), Inches(8), Inches(0.35),
         "Mahalo  \u00b7  SuperMart demo", size=10, color=GREY)
    text(slide, Inches(11.7), Inches(7.0), Inches(1.0), Inches(0.35), str(n),
         size=10, color=GREY, align=PP_ALIGN.RIGHT)


def notes(slide, body):
    slide.notes_slide.notes_text_frame.text = body.strip()


def card(slide, x, y, w, h, title, body, accent=BLUE, title_size=18, body_size=14):
    rect(slide, x, y, w, h, fill=LIGHT, line=LINE)
    rect(slide, x, y, Inches(0.09), h, fill=accent, shape=MSO_SHAPE.RECTANGLE)
    text(slide, x + Inches(0.25), y + Inches(0.15), w - Inches(0.4), Inches(0.5), title,
         size=title_size, bold=True, color=accent)
    body_lines = body if isinstance(body, list) else [body]
    text(slide, x + Inches(0.25), y + Inches(0.65), w - Inches(0.4), h - Inches(0.8),
         body_lines, size=body_size, color=NAVY, spacing=6)


def quote(slide, x, y, w, h, who, role, said, accent):
    rect(slide, x, y, w, h, fill=WHITE, line=LINE)
    rect(slide, x, y, w, Inches(0.09), fill=accent, shape=MSO_SHAPE.RECTANGLE)
    text(slide, x + Inches(0.3), y + Inches(0.3), w - Inches(0.6), Inches(0.4), role.upper(),
         size=12, bold=True, color=accent)
    text(slide, x + Inches(0.3), y + Inches(0.65), w - Inches(0.6), Inches(0.4), who,
         size=18, bold=True)
    text(slide, x + Inches(0.3), y + Inches(1.2), w - Inches(0.6), h - Inches(1.4),
         f"\u201c{said}\u201d", size=16, italic=True, color=GREY)


def prompt_box(slide, x, y, w, h, prompts, label="Type in Mahalo"):
    rect(slide, x, y, w, h, fill=NAVY)
    text(slide, x + Inches(0.3), y + Inches(0.2), w - Inches(0.6), Inches(0.4), label.upper(),
         size=12, bold=True, color=RGBColor(0x9C, 0xC9, 0xEE))
    lines = [(f"\u25b8  {p}", {"color": WHITE}) for p in prompts]
    text(slide, x + Inches(0.3), y + Inches(0.65), w - Inches(0.6), h - Inches(0.8),
         lines, size=15, spacing=10)


def image_slide(img, n, title):
    s = prs.slides.add_slide(BLANK)
    pic = s.shapes.add_picture(str(HERE / img), 0, 0, width=W)
    if pic.height > H:  # keep aspect; centre vertically if taller than the slide
        pic.top = Emu(int((H - pic.height) / 2))
    pic.name = title
    return s


# --------------------------------------------------------------------------- slides
n = 0

# 1. Title -------------------------------------------------------------------
n += 1
s = prs.slides.add_slide(BLANK)
rect(s, 0, 0, W, H, fill=NAVY, shape=MSO_SHAPE.RECTANGLE)
rect(s, Inches(0.8), Inches(2.6), Inches(1.2), Inches(0.08), fill=BLUE, shape=MSO_SHAPE.RECTANGLE)
text(s, Inches(0.8), Inches(2.8), Inches(11.5), Inches(1.2), "Mahalo", size=60, bold=True, color=WHITE)
text(s, Inches(0.8), Inches(3.9), Inches(11.5), Inches(0.8),
     "One assistant for everyone who builds the product", size=26, color=WHITE)
text(s, Inches(0.8), Inches(4.8), Inches(11.5), Inches(0.6),
     "A day at SuperMart: from siloed tools to one connected view", size=18,
     color=RGBColor(0x9C, 0xC9, 0xEE))
notes(s, """
[0:00 - 0:30]
Today I'm not going to start with technology. I'll start with a company, SuperMart, and the
people who build its online store. I'll show you what their day looks like now, then the same
day with Mahalo. Everything after the slides is live.
""")

# 2. Meet SuperMart ------------------------------------------------------------
n += 1
s = prs.slides.add_slide(BLANK)
header(s, "Meet SuperMart", "The business")
text(s, Inches(0.6), Inches(1.6), Inches(6.2), Inches(4.8), [
    ("A fictional online retailer.", {"bold": True, "size": 22}),
    "Customers browse products, fill a cart, sign in, pay and track their order.",
    "Every one of those steps is a separate piece of software, owned by a separate team.",
    "When any one of them slows down, the whole store feels it.",
], size=18, spacing=14)
steps = ["Browse", "Cart", "Sign in", "Pay", "Track order"]
for i, step in enumerate(steps):
    y = Inches(1.6) + Inches(0.95) * i
    rect(s, Inches(7.6), y, Inches(4.9), Inches(0.75), fill=LIGHT, line=LINE)
    text(s, Inches(7.8), y, Inches(0.6), Inches(0.75), str(i + 1), size=20, bold=True,
         color=BLUE, anchor=MSO_ANCHOR.MIDDLE)
    text(s, Inches(8.4), y, Inches(4.0), Inches(0.75), step, size=18, anchor=MSO_ANCHOR.MIDDLE)
footer(s, n)
notes(s, """
[0:30 - 2:00]
SuperMart is a made-up online retailer, but its shape is very real. A customer browses
products, adds them to a cart, signs in, pays, and tracks the order.
Behind each step is a different system with a different team. That's normal and healthy for
building software. The problem is what it does to the people trying to see the whole picture.
""")

# 3. Five teams ---------------------------------------------------------------
n += 1
s = prs.slides.add_slide(BLANK)
header(s, "Five teams, five products", "Who builds the store")
rows = [
    ("Key", "Team", "Code repository", "What it does"),
    ("PROD", "Catalog", "product-service", "Products, search, inventory"),
    ("CART", "Shopping cart", "cart-service", "Coupons, shipping, checkout"),
    ("AUTH", "Accounts", "auth-service", "Login, single sign-on, two-factor"),
    ("PAY", "Payments", "payment-service", "Cards, wallets, refunds, fraud checks"),
    ("ORD", "Orders", "order-service", "Fulfilment, tracking, returns"),
]
tbl = s.shapes.add_table(len(rows), 4, Inches(0.6), Inches(1.7), Inches(12.1), Inches(4.2)).table
widths = [1.4, 2.6, 3.0, 5.1]
for c, wd in enumerate(widths):
    tbl.columns[c].width = Inches(wd)
for r, row in enumerate(rows):
    for c, val in enumerate(row):
        cell = tbl.cell(r, c)
        cell.fill.solid()
        cell.fill.fore_color.rgb = NAVY if r == 0 else (LIGHT if r % 2 else WHITE)
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf = cell.text_frame
        tf.text = ""
        run = tf.paragraphs[0].add_run()
        run.text = val
        _style(run, 16 if r else 14, WHITE if r == 0 else (BLUE if c == 0 else NAVY),
               bold=(r == 0 or c == 0))
text(s, Inches(0.6), Inches(6.1), Inches(12.1), Inches(0.7),
     "Each team tracks work in Jira, logs production incidents in ServiceNow, keeps docs in "
     "Confluence and stores code in git.", size=15, color=GREY)
footer(s, n)
notes(s, """
[2:00 - 3:00]
These short codes will come up in the demo, so here's what they mean.
PROD is the catalog: products, search and stock. CART is the shopping cart: coupons, shipping,
checkout. AUTH is accounts and login. PAY is payments: cards, wallets, refunds and fraud checks.
ORD is orders: fulfilment, tracking and returns.
Each team uses the same four tools: Jira for work, ServiceNow for incidents, Confluence for
docs, and git for code. Four tools times five teams is twenty places to look.
""")

# 4. Infographic: challenges --------------------------------------------------
n += 1
s = image_slide("supermart-challenges.png", n, "SuperMart today: siloed tools")
notes(s, """
[3:00 - 6:00]
This is SuperMart today. Three people, one product, and four disconnected tools in the middle.
David Kim, the executive, wants one answer before each release: who is at risk? Getting it
takes three meetings, and by the time he has it, it's stale.
Marcus Chen, the project manager, plans sprints by copying Jira and ServiceNow into a
spreadsheet and guessing who still has capacity.
Lava, a developer, spends half the morning switching tabs: find my stories, check incidents,
wait for review, update Jira.
Nobody here is doing anything wrong. The tools just don't talk to each other, so people do the
connecting by hand.
""")

# 5. Why it hurts --------------------------------------------------------------
n += 1
s = prs.slides.add_slide(BLANK)
header(s, "Three people, three versions of the same pain", "Why it hurts")
cw, ch, gap = Inches(3.85), Inches(3.4), Inches(0.28)
qs = [
    ("David Kim", "Executive", "Before every release I ask who's at risk. It takes three "
     "meetings, and the answer is already stale.", RED),
    ("Marcus Chen", "Project manager", "To plan a sprint I copy Jira and ServiceNow into a "
     "spreadsheet and guess who still has capacity.", BLUE),
    ("Lava Dev", "Developer", "Half my morning is tab-switching: find my stories, check "
     "incidents, wait for review, update Jira.", GREEN),
]
for i, (who, role, said, acc) in enumerate(qs):
    quote(s, Inches(0.6) + (cw + gap) * i, Inches(1.7), cw, ch, who, role, said, acc)
text(s, Inches(0.6), Inches(5.4), Inches(12.1), Inches(1.3), [
    ("The cost: slow decisions, plans built on guesses, and engineers doing admin instead of "
     "building.", {"bold": True, "size": 18}),
], size=18)
footer(s, n)
notes(s, """
[6:00 - 7:30]
Put plainly, the same gap shows up three ways.
For David it's slow decisions: the data exists, but it takes people and meetings to assemble.
For Marcus it's plans built on guesses: capacity lives in one tool and incidents in another.
For Lava it's lost build time: every status update is a manual step in another tab.
Hold on to these three quotes. In the demo I'll answer each one directly.
""")

# 6. Infographic: connected ----------------------------------------------------
n += 1
s = image_slide("mahalo-connected.png", n, "With Mahalo: everyone connected")
notes(s, """
[7:30 - 9:30]
Here's the same company with Mahalo. One screen, one login, and behind it the same four tools.
Nothing gets replaced. Jira is still Jira and git is still git.
Mahalo sits in the middle and reads from all of them, so each person asks a question in plain
English and gets an answer that already joins the data together.
Why does one screen work for three very different people? Because Mahalo knows who you are.
David sees portfolio-level answers and charts. Marcus sees his projects and plans. Lava sees
his own stories and can write and commit code. Same tool, different view, shared facts.
""")

# 7. Executive demo -----------------------------------------------------------
n += 1
s = prs.slides.add_slide(BLANK)
header(s, "David asks: who's at risk?", "Live demo  \u00b7  Executive")
card(s, Inches(0.6), Inches(1.7), Inches(5.4), Inches(1.6), "The pain",
     "Three meetings to learn which projects are at risk, and the answer is already stale.",
     accent=RED)
card(s, Inches(0.6), Inches(3.5), Inches(5.4), Inches(2.9), "What Mahalo does", [
    "Reads every project's sprint and incidents in one go",
    "Answers in seconds, with a chart when asked",
    "Same live data the teams are using right now",
], accent=GREEN)
prompt_box(s, Inches(6.4), Inches(1.7), Inches(6.3), Inches(4.7), [
    "Show story points completed per project this sprint as a bar chart.",
    "What's our delivery risk across all five projects this sprint?",
    "Which projects have open incidents in ServiceNow right now?",
])
footer(s, n)
notes(s, """
[9:30 - 13:30]  LIVE DEMO - sign in as David Kim (Executive). Logins are in docs/DEMO-LOGINS.md.

1. Type: "Show story points completed per project this sprint as a bar chart."
   Point out: a real chart, built from Jira data across all five projects, no spreadsheet.
2. Type: "What's our delivery risk across all five projects this sprint?"
   Point out: it combines sprint progress with open incidents and calls out the projects to
   watch. This is the "three meetings" question answered in one sentence.
3. Type: "Which projects have open incidents in ServiceNow right now?"
   Point out: same screen, a different system, no tab switch.

Close: David's question took seconds, and the answer is current, not last week's slide.
""")

# 8. PM demo ------------------------------------------------------------------
n += 1
s = prs.slides.add_slide(BLANK)
header(s, "Marcus plans the sprint", "Live demo  \u00b7  Project manager")
card(s, Inches(0.6), Inches(1.7), Inches(5.4), Inches(1.6), "The pain",
     "Copying Jira and ServiceNow into a spreadsheet and guessing capacity.", accent=RED)
card(s, Inches(0.6), Inches(3.5), Inches(5.4), Inches(2.9), "What Mahalo does", [
    "One status view: sprint, pull requests, incidents",
    "Links a story to its pull request",
    "JIRA_ROADMAP skill: a two-sprint plan with capacity checks, computed the same way every run",
], accent=GREEN)
prompt_box(s, Inches(6.4), Inches(1.7), Inches(6.3), Inches(4.7), [
    "Give me a status summary across all my projects \u2014 sprint progress, open PRs, and incidents.",
    "Who is working on what in the payment project right now?",
    "What's the status of PAY-105, and is there a pull request for it?",
    "Open the MahaloJira board",
    "/JIRA_ROADMAP PAY",
])
footer(s, n)
notes(s, """
[13:30 - 18:30]  LIVE DEMO - sign in as Marcus Chen (PM).

1. Type: "Give me a status summary across all my projects — sprint progress, open PRs, and incidents."
   Point out: Jira, git and ServiceNow in one answer.
2. Type: "Who is working on what in the payment project right now?"
3. Type: "What's the status of PAY-105, and is there a pull request for it?"
   Point out: the story and the code are linked for him. No asking a developer.
4. Open the MahaloJira board to show the familiar Jira-style view of the same data.
5. Type: /JIRA_ROADMAP PAY
   Point out the plan:
   - PAY team capacity is 30 points per sprint.
   - Sprint A: 29 of 30 points (PAY-110, PAY-098, PAY-099).
   - Sprint B: 26 of 30 points (PAY-092, PAY-094, PAY-085, PAY-091, PAY-095).
   - It flags people who are overloaded: dev-6 is 16 points over in Sprint A, dev-5 is 2 over
     in Sprint B.
   Why this matters: the totals are calculated in code, not guessed by the AI. Run it twice and
   you get exactly the same answer. It takes a few seconds.
   Current sprint for reference: 34 of 42 committed points done (81%).

Close: this was Marcus's spreadsheet afternoon, done in a few minutes.
""")

# 9. Developer demo -------------------------------------------------------------
n += 1
s = prs.slides.add_slide(BLANK)
header(s, "Lava ships a story without leaving the page", "Live demo  \u00b7  Developer")
card(s, Inches(0.6), Inches(1.7), Inches(5.4), Inches(1.6), "The pain",
     "Half the morning lost to tab-switching and status updates.", accent=RED)
card(s, Inches(0.6), Inches(3.5), Inches(5.4), Inches(2.9), "What Mahalo does", [
    "Shows my assigned stories",
    "Writes the code, reviews it, and commits to a new branch",
    "Asks for my approval before it changes anything",
    "Updates Jira for me",
], accent=GREEN)
prompt_box(s, Inches(6.4), Inches(1.7), Inches(6.3), Inches(4.7), [
    "What's assigned to me right now?",
    "Write the code for PAY-109 \u2026 commit it to the payment-service repo on a new branch.",
    "Approve the change",
    "Move PAY-109 to in progress.",
])
footer(s, n)
notes(s, """
[18:30 - 23:30]  LIVE DEMO - sign in as Lava Dev (Developer).

0. Settings: set the review model to Nova Lite (quick and cheap for the demo).
1. Type: "What's assigned to me right now?"
   Expect PAY-109 and PAY-110.
2. Type: "Write the code for PAY-109 … commit it to the payment-service repo on a new branch."
   (Use the full prompt from docs/DEMO_script.md.)
   Point out: Mahalo writes the code, a second model reviews it, and then it stops and asks.
3. Approve the change.
   Point out: nothing is written to git without a human saying yes.
4. Type: "Move PAY-109 to in progress."
   Point out: the Jira update happened from the same screen.

Close: find the story, write it, review it, commit it, update Jira. One page, no tab switch.
""")

# 10. PM again ------------------------------------------------------------------
n += 1
s = prs.slides.add_slide(BLANK)
header(s, "Marcus sees it straight away", "Live demo  \u00b7  Back to the project manager")
text(s, Inches(0.6), Inches(1.7), Inches(5.6), Inches(4.5), [
    ("The loop closes.", {"bold": True, "size": 22}),
    "The commit Lava just made shows up in Marcus's view.",
    "No stand-up, no status email, no chasing.",
], size=18, spacing=14)
prompt_box(s, Inches(6.4), Inches(1.7), Inches(6.3), Inches(3.2), [
    "What progress has been made on the payment project today?",
    "Show me the latest pull requests and commits for payment-service.",
])
footer(s, n)
notes(s, """
[23:30 - 25:00]  LIVE DEMO - sign back in as Marcus Chen (PM).

1. Type: "What progress has been made on the payment project today?"
2. Type: "Show me the latest pull requests and commits for payment-service."
   Point out: Lava's branch and commit from two minutes ago are already here.

Close: the developer did the work, and the PM knows about it without anyone telling him.
""")

# 11. Built-in trust -------------------------------------------------------------
n += 1
s = prs.slides.add_slide(BLANK)
header(s, "Built-in trust", "Why it's safe to use")
cw, ch = Inches(5.9), Inches(2.25)
items = [
    ("Role-based access", "Each person sees and does only what their role allows. Only a "
     "developer can commit code.", BLUE),
    ("Human approval", "Anything that changes code or tickets pauses and waits for a person to "
     "approve.", GREEN),
    ("Second-opinion review", "Generated code is reviewed by a separate model before it is "
     "shown for approval.", BLUE),
    ("Numbers you can repeat", "Plans and totals are calculated in code, so the same question "
     "gives the same answer.", GREEN),
]
for i, (t, b, acc) in enumerate(items):
    x = Inches(0.6) + (cw + Inches(0.3)) * (i % 2)
    y = Inches(1.7) + (ch + Inches(0.3)) * (i // 2)
    card(s, x, y, cw, ch, t, b, accent=acc, body_size=16)
footer(s, n)
notes(s, """
[25:00 - 26:30]
A common worry with AI assistants is "what if it does something I didn't ask for?"
Four things address that. Access follows your role. Every change waits for a human yes.
Generated code gets a second review before you see it. And where numbers matter, like the
sprint plan, they're calculated in code rather than written by the AI, so they're repeatable.
""")

# 12. Skills ---------------------------------------------------------------------
n += 1
s = prs.slides.add_slide(BLANK)
header(s, "Skills: the team's playbooks, one command away", "Extending Mahalo")
text(s, Inches(0.6), Inches(1.7), Inches(6.2), Inches(4.6), [
    ("A skill is a saved, repeatable task.", {"bold": True, "size": 22}),
    "Type a slash command and Mahalo runs the same steps every time.",
    "Example: /JIRA_ROADMAP PAY builds a two-sprint plan with capacity checks.",
    "Teams can add their own playbooks without changing the product.",
], size=18, spacing=14)
card(s, Inches(7.3), Inches(1.7), Inches(5.4), Inches(4.4), "Ideas for SuperMart", [
    "Release readiness check",
    "Incident hand-off summary",
    "Sprint retro starter",
    "New-starter onboarding guide",
], accent=BLUE, body_size=16)
footer(s, n)
notes(s, """
[26:30 - 27:30]
You saw one skill already: the roadmap. Skills are how a team turns a task it does every week
into one command that runs the same way each time. The examples on the right are ideas, not
built features. Each one is a small addition, not a new project.
""")

# 13. Real vs demo, next steps --------------------------------------------------------
n += 1
s = prs.slides.add_slide(BLANK)
header(s, "What you saw, honestly", "Real vs demo data  \u00b7  What's next")
card(s, Inches(0.6), Inches(1.7), Inches(3.9), Inches(3.0), "Real", [
    "The assistant and its AI models",
    "Git: a real Gitea server with real branches and commits",
    "Role-based login and approvals",
], accent=GREEN, body_size=15)
card(s, Inches(4.7), Inches(1.7), Inches(3.9), Inches(3.0), "Demo data", [
    "Jira, ServiceNow and Confluence are realistic sample data",
    "SuperMart and its people are fictional",
], accent=BLUE, body_size=15)
card(s, Inches(8.8), Inches(1.7), Inches(3.9), Inches(3.0), "Next steps", [
    "Connect a real Jira and ServiceNow",
    "Pick one team for a pilot",
    "Choose two or three skills to build",
], accent=NAVY, body_size=15)
text(s, Inches(0.6), Inches(5.0), Inches(12.1), Inches(1.2),
     "Connecting real systems swaps the data source. The screens, roles and approvals you saw "
     "stay the same.", size=17, color=GREY)
footer(s, n)
notes(s, """
[27:30 - 28:30]
I want to be clear about what was real. The assistant, the models, the logins, the approvals
and the git server are real: the commit Lava made is a real commit on a real branch.
Jira, ServiceNow and Confluence are sample data shaped like SuperMart's. Connecting the real
tools replaces the data source, not the experience.
Suggested next step: one pilot team, real Jira and ServiceNow, and two or three skills they
pick.
""")

# 14. Q&A -----------------------------------------------------------------------------
n += 1
s = prs.slides.add_slide(BLANK)
rect(s, 0, 0, W, H, fill=NAVY, shape=MSO_SHAPE.RECTANGLE)
text(s, Inches(0.8), Inches(2.6), Inches(11.7), Inches(1.2), "Questions", size=54, bold=True,
     color=WHITE)
text(s, Inches(0.8), Inches(3.8), Inches(11.7), Inches(1.6), [
    "David: who's at risk, answered in seconds.",
    "Marcus: a sprint plan without the spreadsheet.",
    "Lava: from story to commit on one page.",
], size=20, color=RGBColor(0x9C, 0xC9, 0xEE), spacing=10)
notes(s, """
[28:30 - 30:00]
Recap the three quotes and how each was answered, then open for questions.
If asked about test coverage or incident root causes: the demo data has no test records, so
don't demo that. Say it's a natural next skill once real systems are connected.
""")

cp = prs.core_properties
cp.title = "Mahalo: a day at SuperMart"
cp.author = cp.last_modified_by = "Mahalo team"
prs.save(OUT)
print(f"wrote {OUT.name} with {len(prs.slides)} slides")
