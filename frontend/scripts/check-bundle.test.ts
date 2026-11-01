import { describe, expect, it } from "vitest";

import { findLeaks } from "./check-bundle.mjs";

const jwt = (payload: object) =>
  [{ alg: "HS256", typ: "JWT" }, payload]
    .map((part) => Buffer.from(JSON.stringify(part)).toString("base64url"))
    .join(".") + ".c2lnbmF0dXJl";

const ANON = jwt({ iss: "supabase", role: "anon" });
const SERVICE = jwt({ iss: "supabase", role: "service_role" });

describe("built bundle check", () => {
  it("accepts a bundle holding only the anon key", () => {
    expect(findLeaks({ "assets/app.js": `const k="${ANON}"` }, {})).toEqual([]);
  });

  it("flags a service-role JWT", () => {
    const leaks = findLeaks({ "assets/app.js": `const k="${SERVICE}"` }, {});
    expect(leaks).toEqual([expect.stringContaining("assets/app.js")]);
  });

  it("flags the value of a server-only secret from the environment", () => {
    const env = { SUPABASE_SERVICE_ROLE_KEY: "sb_secret_abc123xyz" };
    const leaks = findLeaks({ "assets/app.js": 'x="sb_secret_abc123xyz"' }, env);
    expect(leaks).toEqual([expect.stringContaining("SUPABASE_SERVICE_ROLE_KEY")]);
  });

  it("flags the service_role marker and new-style secret keys", () => {
    expect(findLeaks({ "a.js": "role:'service_role'" }, {})).toHaveLength(1);
    expect(findLeaks({ "a.js": 'k="sb_secret_N7UND0UgjKTVK-Uodkm0Hg_xSvEMPvz"' }, {})).toHaveLength(1);
  });
});
