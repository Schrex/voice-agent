import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { fetchUninformed, jobText, officeTime } from "./api";
import { useAuth } from "./App";

/** Refreshes with the queue (architecture §1: every 10 s). */
const REFRESH_MS = 10_000;

/**
 * Uninformed (spec §5 flags, AC9.4): Resolved requests whose Foreman has not been marked
 * Foreman Informed within the threshold, with their count. Oldest Resolved first, as sent.
 * Marking one Foreman Informed (on its page) clears it from here.
 */
export function UninformedList() {
  const { session } = useAuth();
  const uninformed = useQuery({
    queryKey: ["uninformed", session?.accessToken],
    queryFn: () => fetchUninformed(session!.accessToken),
    enabled: !!session,
    refetchInterval: REFRESH_MS,
  });

  return (
    <section aria-labelledby="uninformed">
      {uninformed.isError && !uninformed.data && (
        <p role="alert">Could not load the Uninformed requests.</p>
      )}
      {uninformed.data && (
        <>
          <h2 id="uninformed">Uninformed ({uninformed.data.length})</h2>
          {uninformed.data.length > 0 && (
            <table className="queue" aria-label="Uninformed">
              <thead>
                <tr>
                  <th>Ref</th>
                  <th>Foreman</th>
                  <th>Job</th>
                  <th>Need</th>
                  <th>Outcome</th>
                  <th>Resolved</th>
                </tr>
              </thead>
              <tbody>
                {uninformed.data.map((r) => (
                  <tr key={r.ref}>
                    <td>
                      <Link to={`/requests/${r.ref}`}>{r.ref}</Link>
                    </td>
                    <td>{r.foreman}</td>
                    <td>{jobText(r)}</td>
                    <td>{r.need}</td>
                    <td>{r.outcome}</td>
                    <td>
                      <time dateTime={r.resolved_at}>
                        {officeTime.format(new Date(r.resolved_at))}
                      </time>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}
