"""Build docs/Mahalo_SuperMart_Demo.pptx, the 30-minute business-first demo deck.

Run from the repo root with any Python that has python-pptx installed:

    python docs/demo/build_deck.py

The story follows ONE feature, SuperMart crypto payments (Jira story PAY-109),
through the whole delivery lifecycle: business need -> PM story -> architect
review -> developer build -> CI/CD tests and security -> deploy and support ->
leadership view. Each persona's live demo opens with their login briefing.

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
PALE_BLUE = RGBColor(0x9C, 0xC9, 0xEE)
# Persona colours, matching the infographics.
C_EXEC = RGBColor(0x7B, 0x4F, 0xA0)
C_PM = RGBColor(0x1F, 0x7A, 0x6D)
C_ARCH = RGBColor(0x2A, 0x6F, 0xB0)
C_DEV = RGBColor(0xC4, 0x6A, 0x1B)

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
    text(slide, Inches(0.6), Inches(0.65), Inches(12.1), Inches(0.9), title, size=30, bold=True)


def footer(slide, n):
    text(slide, Inches(0.6), Inches(7.0), Inches(8), Inches(0.35),
         "Mahalo  \u00b7  SuperMart demo", size=10, color=GREY)
    text(slide, Inches(11.7), Inches(7.0), Inches(1.0), Inches(0.35), str(n),
         size=10, color=GREY, align=PP_ALIGN.RIGHT)


def notes(slide, body):
    slide.notes_slide.notes_text_frame.text = body.strip()


def card(slide, x, y, w, h, title, body, accent=BLUE, title_size=17, body_size=14):
    rect(slide, x, y, w, h, fill=LIGHT, line=LINE)
    rect(slide, x, y, Inches(0.09), h, fill=accent, shape=MSO_SHAPE.RECTANGLE)
    text(slide, x + Inches(0.25), y + Inches(0.12), w - Inches(0.4), Inches(0.45), title,
         size=title_size, bold=True, color=accent)
    body_lines = body if isinstance(body, list) else [body]
    text(slide, x + Inches(0.25), y + Inches(0.55), w - Inches(0.4), h - Inches(0.65),
         body_lines, size=body_size, color=NAVY, spacing=5)


def quote(slide, x, y, w, h, who, role, said, accent):
    rect(slide, x, y, w, h, fill=WHITE, line=LINE)
    rect(slide, x, y, w, Inches(0.09), fill=accent, shape=MSO_SHAPE.RECTANGLE)
    text(slide, x + Inches(0.25), y + Inches(0.25), w - Inches(0.5), Inches(0.4), role.upper(),
         size=11, bold=True, color=accent)
    text(slide, x + Inches(0.25), y + Inches(0.55), w - Inches(0.5), Inches(0.4), who,
         size=16, bold=True)
    text(slide, x + Inches(0.25), y + Inches(1.05), w - Inches(0.5), h - Inches(1.2),
         f"\u201c{said}\u201d", size=14, italic=True, color=GREY)


def prompt_box(slide, x, y, w, h, prompts, label="Type in Mahalo", size=14):
    rect(slide, x, y, w, h, fill=NAVY)
    text(slide, x + Inches(0.3), y + Inches(0.18), w - Inches(0.6), Inches(0.4), label.upper(),
         size=12, bold=True, color=PALE_BLUE)
    lines = [(f"\u25b8  {p}", {"color": WHITE}) for p in prompts]
    text(slide, x + Inches(0.3), y + Inches(0.6), w - Inches(0.6), h - Inches(0.7),
         lines, size=size, spacing=9)


def image_slide(img, title):
    s = prs.slides.add_slide(BLANK)
    pic = s.shapes.add_picture(str(HERE / img), 0, 0, width=W)
    if pic.height > H:  # keep aspect; centre vertically if taller than the slide
        pic.top = Emu(int((H - pic.height) / 2))
    pic.name = title
    return s


# The seven lifecycle stages the manager asked to see, and who carries each one.
STAGES = [
    ("Business need", "SuperMart", GREY),
    ("Story", "Marcus, PM", C_PM),
    ("Design review", "Maya, Architect", C_ARCH),
    ("Build", "Lava, Developer", C_DEV),
    ("Test + security", "CI/CD", GREEN),
    ("Deploy + support", "ServiceNow", GREEN),
    ("Leadership view", "David, Exec", C_EXEC),
]


def stage_strip(slide, y, active=None, h=Inches(0.42), big=False):
    """A row of chevrons for the seven stages; `active` (indexes) are filled."""
    x0, total = Inches(0.6), Inches(12.1)
    step = int(total / len(STAGES))
    for i, (name, who, colour) in enumerate(STAGES):
        on = active is None or i in active
        s = slide.shapes.add_shape(MSO_SHAPE.CHEVRON if i else MSO_SHAPE.PENTAGON,
                                   x0 + step * i, y, step + Inches(0.08), h)
        s.fill.solid()
        s.fill.fore_color.rgb = colour if on else LIGHT
        s.line.fill.background()
        s.shadow.inherit = False
        tf = s.text_frame
        tf.margin_left = Inches(0.25 if i else 0.1)
        tf.margin_right = Inches(0.15)
        tf.margin_top = tf.margin_bottom = Inches(0.02)
        tf.word_wrap = True
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = f"{i + 1}  {name}"
        _style(r, 13 if big else 10, WHITE if on else GREY, bold=True)
        if big:
            p2 = tf.add_paragraph()
            p2.alignment = PP_ALIGN.CENTER
            r2 = p2.add_run()
            r2.text = who
            _style(r2, 11, WHITE if on else GREY)


def demo_slide(n, title, kicker, active, pain, does, prompts, accent, prompt_size=13):
    """Standard live-demo slide: stage strip, pain, what Mahalo does, prompts."""
    s = prs.slides.add_slide(BLANK)
    header(s, title, kicker)
    stage_strip(s, Inches(1.5), active)
    card(s, Inches(0.6), Inches(2.1), Inches(5.4), Inches(1.35), "The pain", pain, accent=RED)
    card(s, Inches(0.6), Inches(3.6), Inches(5.4), Inches(3.2), "What Mahalo does", does,
         accent=accent)
    prompt_box(s, Inches(6.3), Inches(2.1), Inches(6.4), Inches(4.7), prompts, size=prompt_size)
    footer(s, n)
    return s


# --------------------------------------------------------------------------- slides
n = 0

# 1. Title -------------------------------------------------------------------
n += 1
s = prs.slides.add_slide(BLANK)
rect(s, 0, 0, W, H, fill=NAVY, shape=MSO_SHAPE.RECTANGLE)
rect(s, Inches(0.8), Inches(2.4), Inches(1.2), Inches(0.08), fill=BLUE, shape=MSO_SHAPE.RECTANGLE)
text(s, Inches(0.8), Inches(2.6), Inches(11.5), Inches(1.2), "Mahalo", size=60, bold=True, color=WHITE)
text(s, Inches(0.8), Inches(3.7), Inches(11.5), Inches(0.8),
     "One assistant for everyone who builds the product", size=26, color=WHITE)
text(s, Inches(0.8), Inches(4.6), Inches(11.5), Inches(0.6),
     "One SuperMart feature, from business need to leadership view", size=18, color=PALE_BLUE)
notes(s, """
[0:00 - 0:30]
Today I'm not starting with technology. I'll start with a company, SuperMart, and one feature it
wants: crypto payments. We'll follow that one feature from the business need, through the story,
the design review, the code, the tests and security scan, the release and support, all the way to
what leadership sees. Five people, one feature, one assistant. Everything after the slides is live.
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
[0:30 - 1:30]
SuperMart is a made-up online retailer, but its shape is very real. A customer browses products,
adds them to a cart, signs in, pays, and tracks the order. Behind each step is a different system
with a different team. That's normal and healthy for building software. The problem is what it does
to the people trying to move one change through all of it.
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
for c, wd in enumerate([1.4, 2.6, 3.0, 5.1]):
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
     "Every team uses the same five systems: Jira for work, Confluence for designs, git for code, "
     "a CI/CD pipeline for tests and security scans, and ServiceNow for releases and incidents.",
     size=15, color=GREY)
footer(s, n)
notes(s, """
[1:30 - 2:30]
These short codes come up in the demo. PROD is the catalog. CART is the shopping cart. AUTH is
accounts and login. PAY is payments: cards, wallets, refunds and fraud checks. ORD is orders.
Our feature, crypto payments, belongs to the PAY team and the payment-service repository.
Every team uses the same five systems: Jira, Confluence, git, the CI/CD pipeline and ServiceNow.
Five systems times five teams is twenty-five places to look.
""")

# 4. Infographic: challenges --------------------------------------------------
n += 1
s = image_slide("supermart-challenges.png", "SuperMart today: siloed tools")
notes(s, """
[2:30 - 4:00]
This is SuperMart today. The people are on the left and right, the disconnected tools in the middle.
Every handoff between them is a meeting, a spreadsheet or a copy-paste.
Nobody here is doing anything wrong. The tools don't talk to each other, so people do the
connecting by hand, and every feature pays that cost at every step.
""")

# 5. Why it hurts: four quotes ------------------------------------------------
n += 1
s = prs.slides.add_slide(BLANK)
header(s, "Four people, four versions of the same pain", "Why it hurts")
cw, ch, gap = Inches(2.9), Inches(3.5), Inches(0.167)
qs = [
    ("Marcus Chen", "Product manager", "To plan a sprint I copy Jira and ServiceNow into a "
     "spreadsheet and guess who still has capacity.", C_PM),
    ("Maya Chaya", "Architect", "I usually see a design after it ships, when it turns up in an "
     "incident.", C_ARCH),
    ("Lava Dev", "Developer", "Half my morning is tab-switching: find my stories, check "
     "reviews, check the pipeline, update Jira.", C_DEV),
    ("David Kim", "Executive", "Before every release I ask where a feature is and who's at risk. "
     "It takes three meetings.", C_EXEC),
]
for i, (who, role, said, acc) in enumerate(qs):
    quote(s, Inches(0.6) + (cw + gap) * i, Inches(1.7), cw, ch, who, role, said, acc)
text(s, Inches(0.6), Inches(5.5), Inches(12.1), Inches(1.2), [
    ("The cost: plans built on guesses, design problems found in production, engineers doing admin, "
     "and leaders who learn about risk last.", {"bold": True, "size": 17}),
], size=17)
footer(s, n)
notes(s, """
[4:00 - 5:30]
Here's the same gap through four people who all touch our crypto-payments feature.
Marcus plans with a spreadsheet. Maya sees the design too late. Lava loses build time to admin.
David learns about risk in meetings.
Hold on to these four quotes. In the demo, each of these people logs in and I'll answer their quote
directly, in the order the feature moves through the company.
""")

# 6. Infographic: connected ----------------------------------------------------
n += 1
s = image_slide("mahalo-connected.png", "With Mahalo: everyone connected")
notes(s, """
[5:30 - 7:00]
Here's the same company with Mahalo. One screen, one login, and behind it the same five systems.
Nothing is replaced: Jira is still Jira, git is still git, and the CI/CD pipeline still runs the
tests and scans. Mahalo reads all of them, so each person asks in plain English and gets an answer
that already joins the data.
Why does one screen work for four very different people? Because Mahalo knows who you are. Each
person gets their own briefing when they log in, their own dashboard, and their own suggestions.
Same tool, different view, shared facts.
""")

# 7. One feature, end to end ----------------------------------------------------
n += 1
s = prs.slides.add_slide(BLANK)
header(s, "One feature, end to end: crypto payments", "The story we'll follow live")
stage_strip(s, Inches(1.75), None, h=Inches(0.95), big=True)
text(s, Inches(0.6), Inches(3.0), Inches(6.0), Inches(3.8), [
    ("The business need", {"bold": True, "size": 20}),
    "SuperMart customers want to pay with Bitcoin and Ethereum.",
    "In Jira this is story PAY-109, Cryptocurrency payment option: 13 points, owned by the PAY team, "
    "assigned to Lava.",
], size=16, spacing=10)
card(s, Inches(7.0), Inches(3.0), Inches(5.7), Inches(3.6), "Watch for", [
    "Each person starts with a briefing: what changed for them since yesterday.",
    "Each handoff shows up for the next person without a meeting.",
    "The pipeline catches a real problem, and everyone sees it.",
    "One question at the end answers every stage.",
], accent=BLUE, body_size=15)
footer(s, n)
notes(s, """
[7:00 - 8:00]
This is the whole lifecycle my manager asked us to show, and who carries each step.
The business wants crypto payments. Marcus turns it into a story and plans it. Maya reviews the
design before any code. Lava builds it. The CI/CD pipeline runs the tests and the security scan.
Ops releases and supports it in ServiceNow. David sees all of it in one place.
I'll log in as each person in turn. Watch for the handoffs: each step shows up for the next person
without anyone sending an email.
""")

# 8. Marcus: story and plan -----------------------------------------------------
n += 1
s = demo_slide(
    n, "Marcus turns the need into a plan", "Live demo  \u00b7  Stages 1-2  \u00b7  Product manager",
    {0, 1},
    "Copying Jira and ServiceNow into a spreadsheet to plan, and guessing capacity.",
    [
        "Briefing at login: what changed in his projects since yesterday",
        "The story and its acceptance criteria, with any linked code",
        "/JIRA_ROADMAP: a two-sprint plan with capacity checks, computed the same way every run",
    ],
    [
        "(Read the \u201cSince yesterday\u201d briefing card)",
        "Give me a status summary across all my projects \u2014 sprint progress, open PRs, and incidents.",
        "What's the status of PAY-109? Show its acceptance criteria.",
        "Open MahaloJira: Current Sprint board and Backlog",
        "/JIRA_ROADMAP PAY",
    ],
    C_PM,
)
notes(s, """
[8:00 - 11:30]  LIVE DEMO - sign in as Marcus Chen (Product Manager). Logins are in docs/DEMO-LOGINS.md.

0. The "Since yesterday" briefing card is at the top of the chat. Read two lines aloud, for example
   the P1 incidents and "PAY-109 assigned to Lava Dev". Point out: no AI call; it's ranked in code
   from Jira, ServiceNow, Confluence, CI/CD and git, so it's instant and the same every time.
1. Type: "Give me a status summary across all my projects — sprint progress, open PRs, and incidents."
   Point out: Jira, git and ServiceNow in one answer.
2. Type: "What's the status of PAY-109? Show its acceptance criteria."
   Expect: To Do, 13 points, Lava Dev; BTC and ETH, QR code flow, automatic conversion to USD,
   15-minute payment window. This is the business need written down as a story.
3. Open MahaloJira (Connections -> Open MahaloJira): Current Sprint board and Backlog tab.
4. Type: /JIRA_ROADMAP PAY
   - Capacity 30 points per sprint.
   - Sprint A: 29 of 30 (PAY-110, PAY-098, PAY-099). Sprint B: 26 of 30.
   - PAY-109 is "not scheduled: exceeds remaining capacity". That's a real planning conversation:
     crypto payments competes with fraud detection (PAY-110) for the same capacity.
   - Overloaded people flagged: dev-6 16 points over in Sprint A, dev-5 2 over in Sprint B.
   - The totals are computed in code, not by the AI: identical on every run.

Close: Marcus's spreadsheet afternoon, in a few minutes. Now the story goes to the architect.
""")

# 9. Maya: design review --------------------------------------------------------
n += 1
s = demo_slide(
    n, "Maya reviews the design before any code", "Live demo  \u00b7  Stage 3  \u00b7  Architect",
    {2},
    "Seeing a design for the first time after it ships, in an incident.",
    [
        "Her own dashboard: change failure rate, security findings, incidents, open PRs",
        "A design review across services: risks, dependencies, gaps",
        "A decision record drafted in chat, downloadable as a file",
        "Her review lands on the Jira story, after her approval",
        "She cannot commit code: only developers can",
    ],
    [
        "(Read the briefing card; open the Dashboard)",
        "Review the design for PAY-109: risks, dependencies and what's missing.",
        "Draft an architecture decision record for adding crypto payments.  \u2192 Download",
        "Add a design-review comment to PAY-109 saying: Design review: use a provider abstraction "
        "and pin the crypto-signing library version.  \u2192 Approve",
    ],
    C_ARCH,
)
notes(s, """
[11:30 - 15:00]  LIVE DEMO - sign in as Maya Chaya (Architect).

0. Briefing card: failed or rolled-back deploys, the SAML SSO design page updated, P1 incidents,
   review comments. It is different from Marcus's: it's about technical health, not sprint progress.
   Open the Dashboard briefly: change failure rate, security findings, incidents with and without a
   linked deployment, open PRs by service. Her own starting view.
1. Type: "Review the design for PAY-109: risks, dependencies and what's missing."
   Point out: it reads the story, the related services and incidents, and writes an architecture
   review (components, risks, gaps, recommendations).
2. Type: "Draft an architecture decision record for adding crypto payments."
   A Download button appears on the document. Click it: a real .md file she can edit and share.
3. Type the design-review comment prompt. An approval card appears: nothing is written to Jira
   until she approves. Approve it.
   Point out: Maya can comment on stories, but if she asks Mahalo to commit code, it refuses. Only
   developers commit.

Close: the design review is done before a single line of code, and it's on the story where the
developer will see it.
""")

# 10. Lava: build ----------------------------------------------------------------
n += 1
s = demo_slide(
    n, "Lava picks it up and ships the code", "Live demo  \u00b7  Stage 4  \u00b7  Developer",
    {3},
    "Half the morning lost to tab-switching, status updates and chasing reviews.",
    [
        "Briefing: PAY-109 assigned to him, and Maya's review comment",
        "Writes the code, has a second AI model review it, then asks before committing",
        "Commits to a new branch in real git",
        "Updates Jira from the same screen",
    ],
    [
        "(Read the briefing: PAY-109 assigned, Maya's comment)",
        "Settings: code-review model = Nova Lite",
        "What's assigned to me right now?",
        "Write the code for PAY-109, the cryptocurrency payment option, and commit it to the "
        "payment-service repo on a new branch.  \u2192 Approve",
        "Move PAY-109 to in progress.  \u2192 Approve",
    ],
    C_DEV,
)
notes(s, """
[15:00 - 19:30]  LIVE DEMO - sign in as Lava Dev (Developer).

0. Briefing card: "PAY-109 assigned to you: Cryptocurrency payment option", and Maya's
   design-review comment from two minutes ago. That's the handoff from architect to developer with
   no meeting and no email. (The briefing caches for up to a minute; if her comment isn't there yet,
   refresh once.)
1. Settings: set the code-review model to Nova Lite.
   Say: "Code is written by one model and reviewed by a different one, so the review is independent."
2. Type: "What's assigned to me right now?"  Expect PAY-109 and PAY-110 among his stories.
3. Type: "Write the code for PAY-109, the cryptocurrency payment option, and commit it to the
   payment-service repo on a new branch."
   - Stage progress: "Generating with Sonnet..." then "Reviewing with Nova Lite...".
   - Trust line: "Generated by Sonnet, reviewed by Nova Lite", with the findings.
   - Approval card for the branch and commit. Approve. Nothing reaches git without a human yes.
4. Type: "Move PAY-109 to in progress." Approve.
Optional proof: open Gitea and show the branch and commit.

Close: find the story, read the review, write the code, review it, commit it, update Jira. One page.
""")

# 11. CI/CD: tests and security -----------------------------------------------------
n += 1
s = demo_slide(
    n, "The pipeline tests it, and catches a problem", "Live demo  \u00b7  Stage 5  \u00b7  CI/CD",
    {4},
    "Test and scan results live in the pipeline tool. Nobody else sees them.",
    [
        "CI/CD runs the tests and security scans. Mahalo does not replace it.",
        "Mahalo reads the results and puts them next to the story",
        "Tests: 209 passed, 0 failed",
        "Dependency scan: 1 high-severity finding in the crypto-signing library, so the release is "
        "blocked",
    ],
    [
        "(Still as Lava)",
        "Did PAY-109 pass its tests and security scan?",
    ],
    GREEN, prompt_size=15,
)
notes(s, """
[19:30 - 21:30]  LIVE DEMO - still signed in as Lava.

1. Type: "Did PAY-109 pass its tests and security scan?"
   Expect: FAILED at the dependency scan.
   - Unit tests 168 passed, integration tests 41 passed: 209 passed, 0 failed.
   - SAST passed with one medium finding (a hard-coded test wallet key in a fixture).
   - Dependency scan: one HIGH finding, a known vulnerability in the crypto-signing library. The
     security gate blocks the release.
   Point out: this is exactly what Maya's review comment warned about ("pin the crypto-signing
   library version"). The design review and the pipeline agree.

Be honest about the data: the answer is labelled "recorded demo data". The pipeline results are
seeded sample runs, not a live pipeline on the commit Lava just made. In a real rollout, Mahalo reads
the team's own CI/CD tool. The point is that the tests and scans run in CI/CD, and Mahalo makes their
results visible to everyone.
""")

# 12. Deploy and support -------------------------------------------------------------
n += 1
s = demo_slide(
    n, "Release and support: where things break", "Live demo  \u00b7  Stage 6  \u00b7  Ops",
    {5},
    "Failed releases and incidents live in ServiceNow, cut off from their stories.",
    [
        "Reads deployments and incidents from ServiceNow, where ops already works",
        "Change failure rate per service",
        "Links an incident back to its deployment and story",
        "Shows which projects have failing pipelines or open findings",
    ],
    [
        "(As Maya, the architect)",
        "Which services have the highest change failure rate?",
        "Which projects have failing pipelines or open security findings?",
        "(Optional) Which projects have open incidents in ServiceNow right now?",
    ],
    GREEN, prompt_size=14,
)
notes(s, """
[21:30 - 23:00]  LIVE DEMO - sign in as Maya Chaya again (or stay as Lava for the first question).

1. Type: "Which services have the highest change failure rate?"
   Point out: answered from ServiceNow deployments (failed or rolled back versus all).
2. Type: "Which projects have failing pipelines or open security findings?"
   Expect a table across all five projects; PAY-109, AUTH-306 and ORD-503 are blocked by high findings.
3. Optional: "Which projects have open incidents in ServiceNow right now?"

Say: ops keeps working in ServiceNow, exactly as today. Mahalo doesn't deploy anything. It connects
each release and incident back to the story and the code, so support starts with context.
""")

# 13. David: leadership view ------------------------------------------------------------
n += 1
s = demo_slide(
    n, "David asks one question", "Live demo  \u00b7  Stage 7  \u00b7  Executive",
    {6},
    "Three meetings to learn where a feature is and who's at risk.",
    [
        "Briefing: portfolio risk only, P1/P2 incidents and failed releases",
        "One answer across every stage of the feature",
        "Charts across all five projects",
    ],
    [
        "(Read the briefing card)",
        "Where is crypto payments? Give me story, code, review, tests, security, deployment and incidents.",
        "Show story points completed per project this sprint as a bar chart.",
        "(Optional) What's our delivery risk across all five projects this sprint?",
    ],
    C_EXEC,
)
notes(s, """
[23:00 - 25:30]  LIVE DEMO - sign in as David Kim (Executive).

0. Briefing card: portfolio risk only. P1 incidents, failed releases. No comments, no commits.
1. Type: "Where is crypto payments? Give me story, code, review, tests, security, deployment and
   incidents."
   Expect one answer: story in progress (Lava), the new branch and commit, the design review comment,
   tests passed, security FAILED on a high dependency finding, not deployed, no incidents yet, and a
   recommendation to fix the finding before release.
   Point out: that's every stage we just walked through, in one answer, in under a minute.
2. Type: "Show story points completed per project this sprint as a bar chart."
3. Optional: "What's our delivery risk across all five projects this sprint?"

Close: David's three meetings, answered in one question, and the answer is current.
""")

# 14. Built-in trust -------------------------------------------------------------
n += 1
s = prs.slides.add_slide(BLANK)
header(s, "Built-in trust", "Why it's safe to use")
cw, ch = Inches(5.9), Inches(1.55)
items = [
    ("Role-based access", "Only developers create branches, commit or open pull requests. "
     "Only the architect adds design-review comments.", BLUE),
    ("Human approval", "Anything that changes code or tickets pauses and waits for a person to "
     "approve.", GREEN),
    ("Second-opinion review", "Generated code is reviewed by a separate AI model before it is "
     "shown for approval.", BLUE),
    ("Numbers you can repeat", "Sprint plans and the login briefing are computed in code, so the "
     "same question gives the same answer.", GREEN),
    ("Honest labels", "Every answer names the systems it used. Seeded demo data is labelled as such.",
     BLUE),
    ("Nothing replaced", "Jira, Confluence, git, CI/CD and ServiceNow stay the systems of record.",
     GREEN),
]
for i, (t, b, acc) in enumerate(items):
    x = Inches(0.6) + (cw + Inches(0.3)) * (i % 2)
    y = Inches(1.6) + (ch + Inches(0.2)) * (i // 2)
    card(s, x, y, cw, ch, t, b, accent=acc, body_size=14)
footer(s, n)
notes(s, """
[25:30 - 26:30]
"What if it does something I didn't ask for?" Six answers. Access follows your role: you saw Maya
comment but not commit. Every change waits for a human yes. Generated code gets a second review.
Where numbers matter, like the sprint plan and the briefing, they're computed in code, so they
repeat. Every answer says where it came from. And the existing tools stay the systems of record.
""")

# 15. Skills ------------------------------------------------------------------------
n += 1
s = prs.slides.add_slide(BLANK)
header(s, "Skills: the team's playbooks, one command away", "Extending Mahalo")
text(s, Inches(0.6), Inches(1.7), Inches(6.2), Inches(4.8), [
    ("A skill is a saved, repeatable task.", {"bold": True, "size": 22}),
    "Type a slash command and Mahalo runs the same steps every time.",
    "Example: /JIRA_ROADMAP PAY builds the two-sprint plan you saw.",
    "Ask Mahalo to draft a new skill: it returns a file you download, edit and upload in the skill "
    "library.",
], size=17, spacing=14)
card(s, Inches(7.3), Inches(1.7), Inches(5.4), Inches(4.4), "Ideas for SuperMart", [
    "Release readiness check",
    "Incident hand-off summary",
    "Sprint retro starter",
    "Security findings digest",
], accent=BLUE, body_size=16)
footer(s, n)
notes(s, """
[26:30 - 27:15]
You saw one skill: the roadmap. Skills turn a task a team does every week into one command that
runs the same way each time. Mahalo can even draft a skill for you: ask for one, download the file,
edit it, upload it. The ideas on the right are not built yet; each is a small addition.
""")

# 16. Real vs demo, next steps --------------------------------------------------------
n += 1
s = prs.slides.add_slide(BLANK)
header(s, "What you saw, honestly", "Real vs demo data  \u00b7  What's next")
card(s, Inches(0.6), Inches(1.7), Inches(3.9), Inches(3.2), "Real", [
    "The assistant and its AI models",
    "Git: a real Gitea server with real branches and commits",
    "Role-based access, approvals, the briefing",
], accent=GREEN, body_size=15)
card(s, Inches(4.7), Inches(1.7), Inches(3.9), Inches(3.2), "Demo data", [
    "Jira, Confluence and ServiceNow are realistic sample data",
    "CI/CD results are seeded sample runs",
    "SuperMart and its people are fictional",
], accent=BLUE, body_size=15)
card(s, Inches(8.8), Inches(1.7), Inches(3.9), Inches(3.2), "Next steps", [
    "Connect a real Jira, ServiceNow and CI/CD tool",
    "Pick one team for a pilot",
    "Choose two or three skills to build",
], accent=NAVY, body_size=15)
text(s, Inches(0.6), Inches(5.2), Inches(12.1), Inches(1.2),
     "Connecting real systems swaps the data source. The screens, roles, approvals and briefings you "
     "saw stay the same.", size=17, color=GREY)
footer(s, n)
notes(s, """
[27:15 - 28:15]
To be clear about what was real: the assistant, the models, the logins, the role checks, the
approvals, the briefing and the git server are real. The commit Lava made is a real commit on a real
branch. Jira, Confluence and ServiceNow are sample data shaped like SuperMart, and the CI/CD results
are seeded sample runs. Connecting the real tools replaces the data source, not the experience.
Suggested next step: one pilot team, their real Jira, ServiceNow and CI/CD, and two or three skills
they pick.
""")

# 17. Q&A -----------------------------------------------------------------------------
n += 1
s = prs.slides.add_slide(BLANK)
rect(s, 0, 0, W, H, fill=NAVY, shape=MSO_SHAPE.RECTANGLE)
text(s, Inches(0.8), Inches(2.2), Inches(11.7), Inches(1.2), "Questions", size=54, bold=True,
     color=WHITE)
text(s, Inches(0.8), Inches(3.4), Inches(11.7), Inches(2.4), [
    "Marcus: a story and a sprint plan without the spreadsheet.",
    "Maya: the design reviewed before the code.",
    "Lava: from story to reviewed commit on one page.",
    "David: every stage of a feature in one answer.",
], size=20, color=PALE_BLUE, spacing=10)
notes(s, """
[28:15 - 30:00]
Recap the four quotes and how each was answered, then open for questions.
If asked about real test coverage or which missing tests caused incidents: the demo data has no test
records beyond the seeded pipeline runs, so don't demo that. Say it's a natural next skill once a
real CI/CD tool is connected.
If asked "where is the ops person?": ops works in ServiceNow as today; Mahalo reads it. An ops
persona is a small addition if a pilot team wants one.
""")

cp = prs.core_properties
cp.title = "Mahalo: one SuperMart feature, end to end"
cp.author = cp.last_modified_by = "Mahalo team"
prs.save(OUT)
print(f"wrote {OUT.name} with {len(prs.slides)} slides")
