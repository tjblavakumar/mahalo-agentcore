import { describe, it, expect } from "vitest";
import {
  CODE_GEN_OPTION,
  REVIEW_OPTIONS,
  DEFAULT_REVIEW_OPTION,
  modelLabel,
} from "./modelConfig";

/**
 * These ids are the client mirror of the server allow-list (agent/model_config.py
 * and api/app/models.py). If the server ids ever change, this test must be
 * updated in the same change — it is the guard that the UI never offers a value
 * the server would reject (NFR-6).
 */
const SERVER_CODE_GEN_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0";
const SERVER_REVIEW_IDS = [
  "us.amazon.nova-lite-v1:0",
  "us.amazon.nova-micro-v1:0",
  "us.anthropic.claude-haiku-4-5-20251001-v1:0",
];
const SERVER_DEFAULT_REVIEW_ID = "us.amazon.nova-lite-v1:0";

describe("modelConfig allow-list", () => {
  it("code-gen option matches the server code-gen id", () => {
    expect(CODE_GEN_OPTION.id).toBe(SERVER_CODE_GEN_ID);
    expect(CODE_GEN_OPTION.label).toBeTruthy();
  });

  it("review option ids match the server review allow-list exactly", () => {
    expect(REVIEW_OPTIONS.map((o) => o.id)).toEqual(SERVER_REVIEW_IDS);
  });

  it("every review option has a friendly label", () => {
    for (const option of REVIEW_OPTIONS) {
      expect(option.label).toBeTruthy();
      expect(option.label).not.toBe(option.id);
    }
  });

  it("default review option is the server default review id", () => {
    expect(DEFAULT_REVIEW_OPTION.id).toBe(SERVER_DEFAULT_REVIEW_ID);
  });

  it("modelLabel resolves known ids and falls back to the id for unknowns", () => {
    expect(modelLabel(SERVER_CODE_GEN_ID)).toBe(CODE_GEN_OPTION.label);
    expect(modelLabel(SERVER_DEFAULT_REVIEW_ID)).toBe(DEFAULT_REVIEW_OPTION.label);
    expect(modelLabel("made-up-id")).toBe("made-up-id");
  });
});
