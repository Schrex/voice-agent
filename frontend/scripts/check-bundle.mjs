// Fails if the built dashboard contains a Supabase service key (ticket #8, architecture §7).
// Usage: node scripts/check-bundle.mjs dist
// Only VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY may reach the browser. CI builds with
// sentinel server-only secrets in the environment, so a leak of their values is caught too.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { pathToFileURL } from "node:url";

/** Server-only variables whose values must never appear in the bundle. */
export const SERVER_ONLY = [
  "SUPABASE_SERVICE_ROLE_KEY",
  "SUPABASE_SERVICE_KEY",
  "SUPABASE_SECRET_KEY",
  "SUPABASE_JWT_SECRET",
];

const JWT = /eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g;
const SECRET_KEY = /sb_secret_[A-Za-z0-9_-]{10,}/;

function jwtRole(token) {
  try {
    const payload = JSON.parse(Buffer.from(token.split(".")[1], "base64url").toString());
    return payload.role;
  } catch {
    return undefined;
  }
}

/**
 * @param {Record<string, string>} files bundle path -> contents
 * @param {Record<string, string | undefined>} env
 * @returns {string[]} one message per leak
 */
export function findLeaks(files, env) {
  const leaks = [];
  for (const [path, text] of Object.entries(files)) {
    for (const name of SERVER_ONLY) {
      const value = env[name];
      if (value && value.length >= 8 && text.includes(value)) {
        leaks.push(`${path}: contains the value of ${name}`);
      }
    }
    for (const token of text.match(JWT) ?? []) {
      if (jwtRole(token) === "service_role") leaks.push(`${path}: contains a service_role JWT`);
    }
    if (text.includes("service_role")) leaks.push(`${path}: mentions service_role`);
    if (SECRET_KEY.test(text)) leaks.push(`${path}: contains an sb_secret_ key`);
  }
  return [...new Set(leaks)];
}

function readTree(dir) {
  const files = {};
  const walk = (d) => {
    for (const name of readdirSync(d)) {
      const full = join(d, name);
      if (statSync(full).isDirectory()) walk(full);
      else files[relative(dir, full)] = readFileSync(full, "latin1");
    }
  };
  walk(dir);
  return files;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  const dir = process.argv[2] ?? "dist";
  const files = readTree(dir);
  const leaks = findLeaks(files, process.env);
  if (Object.keys(files).length === 0) {
    console.error(`check-bundle: ${dir} is empty; build first`);
    process.exit(1);
  }
  if (leaks.length > 0) {
    console.error(["check-bundle: server secrets found in the bundle:", ...leaks].join("\n  "));
    process.exit(1);
  }
  console.log(`check-bundle: ${Object.keys(files).length} files, no service key`);
}
