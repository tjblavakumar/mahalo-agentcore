/**
 * Recognise a design document (ADR, design, design review) in an agent answer so
 * the chat can offer it as a .md download. Detection is by content: a markdown
 * fenced block whose `---` frontmatter holds `doc_type: adr | design |
 * design-review`. Skill files are detected first by `detectSkillBlock`; a block
 * that matches the skill rules (frontmatter `name`) is never classified here, so
 * skill drafts cannot be reclassified. Nothing is parsed as markdown or run: the
 * text is only downloaded.
 *
 * Verified: `parseFrontmatter` takes the whole value after the first colon, so a
 * colon inside `title` is fine and no raw-line fallback is needed.
 */
import { detectSkillBlock } from "./skills/chatBlock";
import { normaliseContent, parseFrontmatter } from "./skills/parse";

export interface DocFileBlock {
  filename: string;
  content: string;
}

const DOC_FENCE_LANGUAGES = new Set(["markdown", "md"]);
const DOC_PREFIX: Record<string, string> = {
  adr: "ADR",
  design: "DESIGN",
  "design-review": "DESIGN-REVIEW",
};
const MAX_SLUG_CHARS = 60;

function slugify(title: string): string {
  const slug = title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, MAX_SLUG_CHARS)
    .replace(/-+$/g, "");
  return slug || "untitled";
}

export function detectDocBlock(language: string | undefined, text: string): DocFileBlock | null {
  if (!language || !DOC_FENCE_LANGUAGES.has(language.toLowerCase())) return null;
  if (detectSkillBlock(language, text) !== null) return null;
  const content = normaliseContent(text);
  const lines = content.split("\n");
  let start = 0;
  while (start < lines.length && !lines[start].trim()) start++;
  if (start >= lines.length || lines[start].trimEnd() !== "---") return null;
  let end = -1;
  for (let i = start + 1; i < lines.length; i++) {
    if (lines[i].trimEnd() === "---") {
      end = i;
      break;
    }
  }
  if (end === -1) return null;
  const values = parseFrontmatter(lines.slice(start + 1, end)).values;
  const docType = (values["doc_type"] ?? "").toLowerCase();
  const prefix = DOC_PREFIX[docType];
  if (!prefix) return null;
  return { filename: `${prefix}-${slugify(values["title"] ?? "")}.md`, content };
}
