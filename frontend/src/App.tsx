import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { fetchMe, type Staff } from "./api";
import type { AuthClient, AuthSession } from "./auth";
import { LoginPage } from "./LoginPage";
import { QueuePage } from "./QueuePage";
import { RequestDetailPage } from "./RequestDetailPage";

type AuthState = { auth: AuthClient; session: AuthSession | null };

const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const state = useContext(AuthContext);
  if (!state) throw new Error("useAuth outside <App>");
  return state;
}

export function App({ auth }: { auth: AuthClient }) {
  const [queryClient] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false } } }));
  const [session, setSession] = useState<AuthSession | null | undefined>(undefined);

  useEffect(() => {
    let active = true;
    // A sign-in/out event that arrives first is newer than the stored session; keep it.
    auth.getSession().then((s) => {
      if (active) setSession((current) => (current === undefined ? s : current));
    });
    const unsubscribe = auth.onChange((s) => setSession(s));
    return () => {
      active = false;
      unsubscribe();
    };
  }, [auth]);

  if (session === undefined) return null; // restoring a stored session

  return (
    <AuthContext.Provider value={{ auth, session }}>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={session ? <Navigate to="/" replace /> : <LoginPage />} />
            <Route
              path="/"
              element={
                <RequireStaff>{(staff) => <QueuePage staff={staff} />}</RequireStaff>
              }
            />
            <Route
              path="/requests/:ref"
              element={
                <RequireStaff>{(staff) => <RequestDetailPage staff={staff} />}</RequireStaff>
              }
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </QueryClientProvider>
    </AuthContext.Provider>
  );
}

/** Shows its children only to a signed-in user the backend accepts as staff. */
function RequireStaff({ children }: { children: (staff: Staff) => ReactNode }) {
  const { auth, session } = useAuth();
  const me = useQuery({
    queryKey: ["me", session?.accessToken],
    queryFn: () => fetchMe(session!.accessToken),
    enabled: !!session,
  });
  const signedOut = me.data?.kind === "signed-out";

  useEffect(() => {
    if (signedOut) void auth.signOut();
  }, [signedOut, auth]);

  if (!session) return <Navigate to="/login" replace />;
  if (me.isError) return <p role="alert">Could not reach the server. Reload to try again.</p>;
  if (!me.data || me.data.kind === "signed-out") return null;
  if (me.data.kind === "not-staff") {
    return (
      <main className="narrow">
        <p role="alert">This account is not on the staff list. Ask an admin to add you.</p>
        <button type="button" onClick={() => void auth.signOut()}>
          Log out
        </button>
      </main>
    );
  }
  return <>{children(me.data.staff)}</>;
}
