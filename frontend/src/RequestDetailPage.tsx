import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import {
  fetchRequestDetail,
  type Actor,
  type RequestDetail,
  type RequestEvent,
  type Staff,
} from "./api";
import { useAuth } from "./App";

/** Every time on the dashboard is shown in the office's zone, whatever the browser's zone. */
const timeFormat = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  weekday: "short",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

/** Spec §5 "source (AI call / coordinator-logged)". */
const SOURCES: Record<RequestDetail["source"], string> = {
  ai_call: "AI call",
  coordinator: "Coordinator-logged",
};

/** Event kinds shown as their glossary word; any other kind is shown as stored. */
const KINDS: Record<string, string> = { recorded: "Recorded" };

/** One request's fields and its full audit history: who, when, what changed. */
export function RequestDetailPage({ staff }: { staff: Staff }) {
  const { auth, session } = useAuth();
  const { ref = "" } = useParams();
  const detail = useQuery({
    queryKey: ["request", ref, session?.accessToken],
    queryFn: () => fetchRequestDetail(session!.accessToken, ref),
    enabled: !!session,
  });

  return (
    <>
      <header className="topbar">
        <Link to="/" className="back">
          Queue
        </Link>
        <span>{staff.name}</span>
        <button type="button" onClick={() => void auth.signOut()}>
          Log out
        </button>
      </header>
      <main>
        {detail.isError && <p role="alert">Could not load the request.</p>}
        {detail.data === null && <p>No such request.</p>}
        {detail.data && <Detail request={detail.data} />}
      </main>
    </>
  );
}

function Detail({ request }: { request: RequestDetail }) {
  const fields: [string, string][] = [
    ["Foreman", request.foreman],
    ["Job", request.job],
    ["Category", request.category],
    ["Need", request.need],
    ["Quantity", quantity(request)],
    ["Needed-by", request.needed_by ?? "—"],
    ["Urgency", request.urgency ?? "—"],
    ["Status", request.status],
    ["Source", SOURCES[request.source]],
    ["Recorded", timeFormat.format(new Date(request.recorded_at))],
  ];
  return (
    <>
      <h1>{request.ref}</h1>
      <dl className="fields" role="group" aria-label="Fields">
        {fields.map(([term, value]) => (
          <div key={term}>
            <dt>{term}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <h2 id="history">History</h2>
      <table className="history" aria-labelledby="history">
        <thead>
          <tr>
            <th>When</th>
            <th>Who</th>
            <th>What</th>
            <th>Changes</th>
          </tr>
        </thead>
        <tbody>
          {request.events.map((e, i) => (
            <tr key={i}>
              <td>
                <time dateTime={e.at}>{timeFormat.format(new Date(e.at))}</time>
              </td>
              <td>{who(e.actor)}</td>
              <td>{KINDS[e.kind] ?? e.kind}</td>
              <td>
                <Changes event={e} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

/** The changed fields: "field: value" on creation, else "field: before → after". */
function Changes({ event }: { event: RequestEvent }) {
  const before = event.before;
  const after = event.after ?? {};
  const names = [...new Set([...Object.keys(before ?? {}), ...Object.keys(after)])];
  return (
    <ul className="changes">
      {names.map((name) => (
        <li key={name}>
          {name}:{" "}
          {before === null ? show(after[name]) : `${show(before[name])} → ${show(after[name])}`}
        </li>
      ))}
    </ul>
  );
}

function show(value: unknown): string {
  if (value === null || value === undefined) return "—";
  return typeof value === "string" ? value : JSON.stringify(value);
}

function who(actor: Actor): string {
  if (actor.type === "agent") return "Agent";
  if (actor.type === "system") return "System";
  return actor.name ?? actor.id ?? "Staff";
}

function quantity(r: RequestDetail): string {
  if (r.quantity === null) return "—";
  return r.unit ? `${r.quantity} ${r.unit}` : r.quantity;
}
