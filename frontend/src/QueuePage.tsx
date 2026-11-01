import { Link } from "react-router-dom";

import type { Staff } from "./api";
import { useAuth } from "./App";

/** The request queue. Empty until the queue ticket (#9) fills it from `GET /api/requests`. */
export function QueuePage({ staff }: { staff: Staff }) {
  const { auth } = useAuth();
  return (
    <>
      <header className="topbar">
        {staff.role === "admin" && <Link to="/admin">Admin</Link>}
        <span>{staff.name}</span>
        <button type="button" onClick={() => void auth.signOut()}>
          Log out
        </button>
      </header>
      <main>
        <h1>Queue</h1>
        <p>No requests.</p>
      </main>
    </>
  );
}
