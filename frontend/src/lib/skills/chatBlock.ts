/**
 * Recognise a skill file in an agent answer and save it as a .md file.
 * Detection is by content, with no marker: a markdown fenced block whose text
 * starts with `---` frontmatter holding a `name`. The file name is derived from
 * that name (jira-roadmap -> JIRA_ROADMAP_SKILL.md), the inverse of the rule that
 * the name equals the command lowercased with hyphens. Validation and the user's
 * confirmation still happen in the upload flow.
 */
import { FILENAME_SUFFIX, commandNameFromFilename, normaliseContent, parseFrontmatter } from "./parse";

export interface SkillFileBlock {
  filename: string;
  content: string;
}

const SKILL_FENCE_LANGUAGES = new Set(["markdown", "md"]);

export function detectSkillBlock(language: string | undefined, text: string): SkillFileBlock | null {
  if (!language || !SKILL_FENCE_LANGUAGES.has(language.toLowerCase())) return null;
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
  const name = parseFrontmatter(lines.slice(start + 1, end)).values["name"];
  if (!name) return null;
  const filename = `${name.toUpperCase().replace(/-/g, "_")}${FILENAME_SUFFIX}`;
  if (commandNameFromFilename(filename) === null) return null;
  return { filename, content };
}

/** Save the skill text to the user's computer as a .md file. */
export function downloadSkillFile(block: SkillFileBlock): void {
  const url = URL.createObjectURL(new Blob([block.content], { type: "text/markdown;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = block.filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
