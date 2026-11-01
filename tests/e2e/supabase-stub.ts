import { createHmac } from "node:crypto";

import type { Page } from "@playwright/test";

/** The backend under test verifies tokens with this secret (see frontend/playwright.config.ts). */
export const E2E_JWT_SECRET = "e2e-only-jwt-secret-not-used-anywhere-else";
/** The backend under test accepts call-start webhooks with this secret. */
export const E2E_HOOK_SECRET = "e2e-only-hook-secret";
/** Never resolved: every request to it is answered by `stubSupabaseAuth`. */
export const E2E_SUPABASE_URL = "http://supabase.e2e.invalid";

export type StubUser = { id: string; email: string; password: string };

const b64url = (value: object) => Buffer.from(JSON.stringify(value)).toString("base64url");

/** An access token shaped like Supabase's: HS256, aud "authenticated", sub = user id. */
export function accessToken(user: StubUser): string {
  const now = Math.floor(Date.now() / 1000);
  const head = b64url({ alg: "HS256", typ: "JWT" });
  const body = b64url({
    sub: user.id,
    aud: "authenticated",
    role: "authenticated",
    email: user.email,
    iat: now,
    exp: now + 3600,
  });
  const sig = createHmac("sha256", E2E_JWT_SECRET).update(`${head}.${body}`).digest("base64url");
  return `${head}.${body}.${sig}`;
}

/** Answers Supabase Auth's password sign-in and logout endpoints for the given users. */
export async function stubSupabaseAuth(page: Page, users: StubUser[]): Promise<void> {
  await page.route(`${E2E_SUPABASE_URL}/auth/v1/token?grant_type=password`, async (route) => {
    const { email, password } = route.request().postDataJSON() as Record<string, string>;
    const user = users.find((u) => u.email === email && u.password === password);
    if (!user) {
      await route.fulfill({
        status: 400,
        json: { error: "invalid_grant", error_description: "Invalid login credentials" },
      });
      return;
    }
    const now = Math.floor(Date.now() / 1000);
    await route.fulfill({
      json: {
        access_token: accessToken(user),
        token_type: "bearer",
        expires_in: 3600,
        expires_at: now + 3600,
        refresh_token: "e2e-refresh",
        user: {
          id: user.id,
          aud: "authenticated",
          role: "authenticated",
          email: user.email,
          app_metadata: { provider: "email" },
          user_metadata: {},
          created_at: new Date().toISOString(),
        },
      },
    });
  });
  await page.route(`${E2E_SUPABASE_URL}/auth/v1/logout**`, (route) =>
    route.fulfill({ status: 204 }),
  );
}
