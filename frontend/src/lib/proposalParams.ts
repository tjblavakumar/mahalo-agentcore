/**
 * Pure helper that classifies a proposal param value for display, so the
 * ProposalCard can show file contents for review instead of "[object Object]".
 */

export interface ProposalFile {
  path: string;
  content: string;
  lineCount: number;
}

export type ParamView =
  | { kind: "files"; files: ProposalFile[] }
  | { kind: "json"; text: string }
  | { kind: "text"; text: string };

function countLines(content: string): number {
  return content === "" ? 0 : content.split("\n").length;
}

function isFileEntry(v: unknown): v is { path: string; content: string } {
  if (typeof v !== "object" || v === null || Array.isArray(v)) return false;
  const o = v as Record<string, unknown>;
  return typeof o.path === "string" && typeof o.content === "string";
}

export function classifyParam(value: unknown): ParamView {
  if (Array.isArray(value) && value.length > 0 && value.every(isFileEntry)) {
    return {
      kind: "files",
      files: value.map((f) => ({
        path: f.path,
        content: f.content,
        lineCount: countLines(f.content),
      })),
    };
  }
  if (typeof value === "object" && value !== null) {
    return { kind: "json", text: JSON.stringify(value, null, 2) };
  }
  return { kind: "text", text: String(value) };
}
