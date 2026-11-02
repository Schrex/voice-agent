import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { fetchDrafts, officeTime, recordDraft, resolveRequest, type Draft, type Staff } from "./api";
import { useAuth } from "./App";

const REFRESH_MS = 10_000;

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
  // #28: a Draft nobody will record is discarded by resolving it as Withdrawn (never deleted).
  const withdraw = useMutation({
    mutationFn: ({ ref, explanation }: { ref: string; explanation: string }) =>
      resolveRequest(token, ref, "Withdrawn", explanation),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["drafts"] }),
  });
  const busy = record.isPending || withdraw.isPending;

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
        <p>
          Not confirmed by the Foreman. Record one to put it in the queue, or resolve it as
          Withdrawn if it is not needed.
        </p>
        {record.isError && (
          <p role="alert">{record.variables} could not be recorded. Reload and try again.</p>
        )}
        {withdraw.isError && (
          <p role="alert">
            {withdraw.variables?.ref} could not be resolved. Reload and try again.
          </p>
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
                  busy={busy}
                  onRecord={() => record.mutate(draft.ref)}
                  onWithdraw={(explanation) => withdraw.mutate({ ref: draft.ref, explanation })}
                />
              ))}
            </tbody>
          </table>
        )}
      </main>
    </>
  );
}

function DraftRow({
  draft,
  busy,
  onRecord,
  onWithdraw,
}: {
  draft: Draft;
  busy: boolean;
  onRecord: () => void;
  onWithdraw: (explanation: string) => void;
}) {
  const [explanation, setExplanation] = useState("");
  const quantity = [draft.quantity, draft.unit].filter(Boolean).join(" ");
  return (
    <tr>
      <td>{draft.ref}</td>
      <td>{draft.foreman}</td>
      <td>
        {draft.job ?? (
          <>
            <span className="flag">Unmatched</span>:{" "}
            {draft.job_spoken ? `“${draft.job_spoken}”` : "not said"}
          </>
        )}
      </td>
      <td>{draft.category}</td>
      <td>{draft.need}</td>
      <td>{quantity}</td>
      <td>{draft.needed_by_spoken ?? ""}</td>
      <td>{draft.call_started_at ? officeTime.format(new Date(draft.call_started_at)) : ""}</td>
      <td>{draft.call_summary ?? ""}</td>
      <td>
        <button type="button" disabled={busy} onClick={onRecord}>
          Record
        </button>
        <form
          aria-label={`Withdraw ${draft.ref}`}
          onSubmit={(e) => {
            e.preventDefault();
            if (explanation.trim() !== "") onWithdraw(explanation);
          }}
        >
          <label>
            Explanation
            <input value={explanation} onChange={(e) => setExplanation(e.target.value)} />
          </label>
          <button type="submit" disabled={busy || explanation.trim() === ""}>
            Resolve as Withdrawn
          </button>
        </form>
      </td>
    </tr>
  );
}
