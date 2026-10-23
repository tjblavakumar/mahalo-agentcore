/**
 * The single source of truth for the demo's hardcoded persona login.
 *
 * Security is explicitly out of scope for this demo (single user, mock data, no
 * live systems). There is no hashing and no token: a plaintext userid/password
 * check gates the UI and selects a persona. Each persona maps to exactly the two
 * fields the Runtime already consumes — `developerId` and `role` — using the real
 * dev-ids from the Jira seed data and the three `ROLE_PROMPTS` keys.
 *
 * This table is the client-side mirror of the server-side table in
 * `api/app/auth.py` (`_PERSONA_MAP`). Keep the two in sync by hand. Only the
 * `personaId` is ever persisted or sent to the API (as the `X-Mahalo-Persona`
 * header); the `password` never leaves the browser.
 */

import type { UserRole } from "@/types";

export type PersonaId = "pm" | "dev" | "exec";

export interface Persona {
  /** The X-Mahalo-Persona header value. */
  personaId: PersonaId;
  /** Login id. */
  userid: string;
  /** Demo-only plaintext password (security out of scope). */
  password: string;
  /** Shown in the UI header. */
  displayName: string;
  /** Human label: "Product Manager" | "Developer" | "Executive". */
  personaLabel: string;
  /** Backend developer_id: dev-1 | dev-6 | dev-5. */
  developerId: string;
  /** Backend role: product_manager | developer | executive. */
  role: UserRole;
}

export const PERSONAS: Record<PersonaId, Persona> = {
  pm: {
    personaId: "pm",
    userid: "pm",
    password: "pm123",
    displayName: "Marcus Chen",
    personaLabel: "Product Manager",
    developerId: "dev-1",
    role: "product_manager",
  },
  dev: {
    personaId: "dev",
    userid: "dev",
    password: "dev123",
    displayName: "Lava Dev",
    personaLabel: "Developer",
    developerId: "dev-6",
    role: "developer",
  },
  exec: {
    personaId: "exec",
    userid: "exec",
    password: "exec123",
    displayName: "David Kim",
    personaLabel: "Executive",
    developerId: "dev-5",
    role: "executive",
  },
};

/** Pure credential check used by the login form. Returns the matching persona or null. */
export function authenticate(userid: string, password: string): Persona | null {
  const match = Object.values(PERSONAS).find(
    (p) => p.userid === userid && p.password === password,
  );
  return match ?? null;
}
