import { defineConfig, devices } from "@playwright/test";

import { E2E_HOOK_SECRET, E2E_TOOL_SECRET } from "../tests/e2e/agent-stub";
import { E2E_JWT_SECRET, E2E_SUPABASE_URL } from "../tests/e2e/supabase-stub";

// P-tests (architecture §9 layer 4). The real backend serves a real build; only Supabase Auth's
// HTTP API is stubbed in the browser (tests/e2e/supabase-stub.ts), so no Supabase account is
// needed. Browsers come from PLAYWRIGHT_BROWSERS_PATH; never run `playwright install` here.
// Needs E2E_DATABASE_URL: a disposable Postgres database (migrated and seeded on start).
const port = process.env.E2E_PORT ?? "8765";

export default defineConfig({
  testDir: "../tests/e2e",
  fullyParallel: false,
  workers: 1,
  reporter: process.env.CI ? "list" : "line",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run build && bash ../tests/e2e/serve.sh",
    url: `http://127.0.0.1:${port}/healthz`,
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      E2E_PORT: port,
      SUPABASE_JWT_SECRET: E2E_JWT_SECRET,
      HOOK_SECRET: E2E_HOOK_SECRET,
      TOOL_SECRET: E2E_TOOL_SECRET,
      OFFICE_MAIN_NUMBER: "585-555-0100",
      VITE_SUPABASE_URL: E2E_SUPABASE_URL,
      VITE_SUPABASE_ANON_KEY: "e2e-anon-key",
    },
  },
});
