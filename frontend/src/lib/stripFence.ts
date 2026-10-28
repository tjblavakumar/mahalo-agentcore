/**
 * Shared helper to strip one surrounding markdown code fence from an agent reply.
 *
 * Extracted from `vizEnvelope.ts` so both the viz parser and the idea parser
 * (`ideaEnvelope.ts`) share one byte-identical implementation. Pure string ->
 * string, no DOM.
 */

/** Strip at most one surrounding ```/```json code fence, then trim. */
export function stripFence(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed.startsWith("```")) {
    return trimmed;
  }
  // Drop the first line (``` or ```json) and a trailing ``` line if present.
  const lines = trimmed.split("\n");
  lines.shift(); // opening fence line
  if (lines.length > 0 && lines[lines.length - 1].trim().startsWith("```")) {
    lines.pop();
  }
  return lines.join("\n").trim();
}
