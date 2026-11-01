import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { fetchDrafts, recordDraft, type Draft, type Staff } from "./api";
import { useAuth } from "./App";

const REFRESH_MS = 10_000;

/** Every time on the dashboard is shown in the office's zone, whatever the browser's zone. */
const callFormat = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  weekday: "short",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

/** Drafts: Requests the Foreman did not confirm (hang-up, drop, Transfer). Kept out of the queue. */
export function DraftsPage({ staff }: { staff: Staff }) {
  const { auth, session } = useAuth();
  const queryClient = useQueryClient();
  const token = session!.accessToken;
  const drafts = useQuery({
    queryKey: ["drafts", token],
    queryFn: () => fetchDrafts(token),
    refetchInterval: REFRESH_MS,
  });
  const record = useMutation({
    mutationFn: (ref: string) => recordDraft(token, ref),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["drafts"] }),
  });

  return (
    <>
      <header className="topbar">
        <nav>
          <Link to="/">Queue</Link>
        </nav>
        <span>{staff.name}</span>
        <button type="button" onClick={() => void auth.signOut()}>
          Log out
        </button>
      </header>
      <main>
        <h1>Drafts</h1>
        <p>Not confirmed by the Foreman. Record one to put it in the queue.</p>
        {record.isError && (
          <p role="alert">{record.variables} could not be recorded. Reload and try again.</p>
        )}
        {drafts.isError && !drafts.data && <p role="alert">Could not load the Drafts.</p>}
        {drafts.data && drafts.data.length === 0 && <p>No Drafts.</p>}
        {drafts.data && drafts.data.length > 0 && (
          <table className="drafts">
            <thead>
              <tr>
                <th>Ref</th>
                <th>Foreman</th>
                <th>Job</th>
                <th>Category</th>
                <th>Need</th>
                <th>Quantity</th>
                <th>Needed-by</th>
                <th>Call</th>
                <th>Summary</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {drafts.data.map((draft) => (
                <DraftRow
                  key={draft.ref}
                  draft={draft}
                  busy={record.isPending}
                  onRecord={() => record.mutate(draft.ref)}
                />
              ))}
            </tbody>
          </table>
        )}
      </main>
    </>
  );
}

function DraftRow({ draft, busy, onRecord }: { draft: Draft; busy: boolean; onRecord: () => void }) {
  const quantity = [draft.quantity, draft.unit].filter(Boolean).join(" ");
  return (
    <tr>
      <td>{draft.ref}</td>
      <td>{draft.foreman}</td>
      <td>{draft.job ?? (draft.job_spoken ? `“${draft.job_spoken}” (no Job matched)` : "")}</td>
      <td>{draft.category}</td>
      <td>{draft.need}</td>
      <td>{quantity}</td>
      <td>{draft.needed_by_spoken ?? ""}</td>
      <td>{draft.call_started_at ? callFormat.format(new Date(draft.call_started_at)) : ""}</td>
      <td>{draft.call_summary ?? ""}</td>
      <td>
        <button
          type="button"
          disabled={busy || draft.job === null}
          title={draft.job === null ? "The Job is not known; it can be recorded once a Job is set." : undefined}
          onClick={onRecord}
        >
          Record
        </button>
      </td>
    </tr>
  );
}
