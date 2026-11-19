import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  SKILL_CHECK_KEYS,
  SKILL_DETAIL_KEYS,
  SKILL_LIMITS_KEYS,
  SKILL_PUT_KEYS,
  SKILL_RUN_KEYS,
  SKILL_SUMMARY_KEYS,
  SKILLS_LIST_KEYS,
  TYPICAL_RUN_SECONDS,
  type SkillCheck,
  type SkillPutResponse,
  type SkillRunInfo,
  type SkillsListResponse,
} from "./types";

function load<T>(name: string): T {
  const path = join(process.cwd(), "src", "lib", "skills", "__fixtures__", name);
  return JSON.parse(readFileSync(path, "utf-8").replace(/^\ufeff/, "")) as T;
}

const sorted = (keys: readonly string[]) => [...keys].sort();
const keysOf = (o: object) => Object.keys(o).sort();

describe("golden fixtures match the key registry", () => {
  it("skill_check", () => {
    const g = load<SkillCheck>("skill_check.golden.json");
    expect(keysOf(g)).toEqual(sorted(SKILL_CHECK_KEYS.top));
    for (const s of g.steps) expect(keysOf(s)).toEqual(sorted(SKILL_CHECK_KEYS.step));
    for (const gap of g.gaps) expect(keysOf(gap)).toEqual(sorted(SKILL_CHECK_KEYS.gap));
    for (const a of g.required_arguments) {
      expect(keysOf(a)).toEqual(sorted(SKILL_CHECK_KEYS.argument));
    }
  });

  it("skill_run", () => {
    expect(keysOf(load<SkillRunInfo>("skill_run.golden.json"))).toEqual(sorted(SKILL_RUN_KEYS));
  });

  it("skills_list", () => {
    const g = load<SkillsListResponse>("skills_list.golden.json");
    expect(keysOf(g)).toEqual(sorted(SKILLS_LIST_KEYS));
    for (const s of g.skills) expect(keysOf(s)).toEqual(sorted(SKILL_SUMMARY_KEYS));
    expect(keysOf(g.limits)).toEqual(sorted(SKILL_LIMITS_KEYS));
  });

  it("skill_put", () => {
    const g = load<SkillPutResponse>("skill_put.golden.json");
    expect(keysOf(g)).toEqual(sorted(SKILL_PUT_KEYS));
    expect(keysOf(g.skill)).toEqual(sorted(SKILL_DETAIL_KEYS));
  });

  it("hides the typical run time until it is measured", () => {
    expect(TYPICAL_RUN_SECONDS).toBeNull();
  });
});
