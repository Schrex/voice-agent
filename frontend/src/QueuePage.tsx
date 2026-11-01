import { useQuery } from "@tanstack/react-query";

import { fetchQueue, type QueueRequest, type Staff } from "./api";
import { useAuth } from "./App";

/** How often the queue refetches (spec J9 / architecture §1: refresh every 10 s). */
const REFRESH_MS = 10_000;

/** Every time on the dashboard is shown in the office's zone, whatever the browser's zone. */
const recordedFormat = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  weekday: "short",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

/** Open requests (spec J9), sorted by the backend: urgency, then oldest first. */
export function QueuePage({ staff }: { staff: Staff }) {
  const { auth, session } = useAuth();
  const queue = useQuery({
    queryKey: ["queue", session?.accessToken],
    queryFn: () => fetchQueue(session!.accessToken),
    enabled: !!session,
    refetchInterval: REFRESH_MS,
  });

  return (
    <>
      <header className="topbar">
        <span>{staff.name}</span>
        <button type="button" onClick={() => void auth.signOut()}>
          Log out
        </button>
      </header>
      <main>
        <h1>Queue</h1>
        {queue.isError && !queue.data && (
          <p role="alert">Could not load the queue.</p>
        )}
        {queue.data && queue.data.length === 0 && <p>No requests.</p>}
        {queue.data && queue.data.length > 0 && <QueueTable requests={queue.data} now={queue.dataUpdatedAt} />}
      </main>
    </>
  );
}

/** Ages are as of the last refresh (`now`), so they advance with every refetch. */
function QueueTable({ requests, now }: { requests: QueueRequest[]; now: number }) {
  return (
    <table className="queue">
      <thead>
        <tr>
          <th>Ref</th>
          <th>Job</th>
          <th>Need</th>
          <th>Quantity</th>
          <th>Needed-by</th>
          <th>Urgency</th>
          <th>Status</th>
          <th>Age</th>
        </tr>
      </thead>
      <tbody>
        {requests.map((r) => (
          <tr key={r.ref}>
            <td>{r.ref}</td>
            <td>{r.job}</td>
            <td>{r.need}</td>
            <td>{quantity(r)}</td>
            <td>{r.needed_by ?? "—"}</td>
            <td>{r.urgency ?? "—"}</td>
            <td>{r.status}</td>
            <td>
              {age(now - Date.parse(r.recorded_at))}
              <time className="recorded" dateTime={r.recorded_at}>
                Recorded {recordedFormat.format(new Date(r.recorded_at))}
              </time>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function quantity(r: QueueRequest): string {
  if (r.quantity === null) return "—";
  return r.unit ? `${r.quantity} ${r.unit}` : r.quantity;
}

/** "0m", "15m", "2h 5m", "3d 5h". */
function age(ms: number): string {
  const minutes = Math.max(0, Math.floor(ms / 60_000));
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ${minutes % 60}m`;
  return `${Math.floor(hours / 24)}d ${hours % 24}h`;
}
