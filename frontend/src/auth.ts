import type { SupabaseClient } from "@supabase/supabase-js";

/** What the dashboard needs from a login session: the token it sends to `/api`. */
export type AuthSession = { accessToken: string };

/**
 * Login only (ADR 0005): Supabase Auth issues the token; every read and write goes through
 * the backend, which verifies it. Tests pass a fake.
 */
export interface AuthClient {
  getSession(): Promise<AuthSession | null>;
  onChange(listener: (session: AuthSession | null) => void): () => void;
  signIn(email: string, password: string): Promise<{ error: string | null }>;
  signOut(): Promise<void>;
}

export function supabaseAuth(client: SupabaseClient): AuthClient {
  const toSession = (s: { access_token: string } | null): AuthSession | null =>
    s ? { accessToken: s.access_token } : null;
  return {
    async getSession() {
      const { data } = await client.auth.getSession();
      return toSession(data.session);
    },
    onChange(listener) {
      const { data } = client.auth.onAuthStateChange((_event, session) =>
        listener(toSession(session)),
      );
      return () => data.subscription.unsubscribe();
    },
    async signIn(email, password) {
      const { error } = await client.auth.signInWithPassword({ email, password });
      return { error: error ? error.message : null };
    },
    async signOut() {
      await client.auth.signOut();
    },
  };
}
