import { describe, it, expect } from "vitest";
import { PERSONAS, authenticate } from "./personas";

describe("authenticate (demo persona credential table)", () => {
  it("maps pm/pm123 to the Product Manager persona (dev-1)", () => {
    const p = authenticate("pm", "pm123");
    expect(p).not.toBeNull();
    expect(p?.personaId).toBe("pm");
    expect(p?.developerId).toBe("dev-1");
    expect(p?.role).toBe("product_manager");
  });

  it("maps dev/dev123 to the Developer persona (dev-6)", () => {
    const p = authenticate("dev", "dev123");
    expect(p).not.toBeNull();
    expect(p?.personaId).toBe("dev");
    expect(p?.developerId).toBe("dev-6");
    expect(p?.role).toBe("developer");
  });

  it("maps exec/exec123 to the Executive persona (dev-5)", () => {
    const p = authenticate("exec", "exec123");
    expect(p).not.toBeNull();
    expect(p?.personaId).toBe("exec");
    expect(p?.developerId).toBe("dev-5");
    expect(p?.role).toBe("executive");
  });

  it("maps arch/arch123 to the Architect persona Maya Chaya (dev-7)", () => {
    const p = authenticate("arch", "arch123");
    expect(p).not.toBeNull();
    expect(p?.personaId).toBe("arch");
    expect(p?.displayName).toBe("Maya Chaya");
    expect(p?.personaLabel).toBe("Architect");
    expect(p?.developerId).toBe("dev-7");
    expect(p?.role).toBe("architect");
  });

  it("lists personas in lifecycle order", () => {
    expect(Object.values(PERSONAS).map((p) => p.personaId)).toEqual(["pm", "arch", "dev", "exec"]);
  });

  it("returns null for a wrong password", () => {
    expect(authenticate("pm", "wrong")).toBeNull();
  });

  it("returns null for an unknown userid", () => {
    expect(authenticate("ghost", "pm123")).toBeNull();
  });
});
