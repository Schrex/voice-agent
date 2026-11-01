import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { fetchFailedAlerts, officeTime, type FailedAlert } from "./api";
import { useAuth } from "./App";

const REFRESH_MS = 10_000;

const KIND: Record<FailedAlert["kind"], string> = {
  today_new: "Today",
  callback: "Callback",
  emergency: "Emergency",
  overdue: "Overdue",
  transfer: "Transfer",
  eod_summary: "End-of-day",
};

const CHANNEL: Record<FailedAlert["channel"], string> = {
  sms: "SMS",
  email: "email",
  popup: "pop-up",
};

/** Alerts that could not be sent (e.g. nobody on duty), so the office can act on them. */
export function FailedAlerts() {
  const { session } = useAuth();
  const failed = useQuery({
    queryKey: ["failed-alerts", session?.accessToken],
    queryFn: () => fetchFailedAlerts(session!.accessToken),
    enabled: !!session,
    refetchInterval: REFRESH_MS,
  });
  if (!failed.data || failed.data.length === 0) return null;
  return (
    <section role="alert" aria-label="Alerts not sent" className="failed-alerts">
      <h2>Alerts not sent</h2>
      <ul>
        {failed.data.map((a, i) => (
          <li key={`${a.ref}-${a.kind}-${a.at}-${i}`}>
            {KIND[a.kind]} {CHANNEL[a.channel]} for{" "}
            {a.ref ? <Link to={`/requests/${a.ref}`}>{a.ref}</Link> : "—"} not sent (
            {officeTime.format(new Date(a.at))}){a.detail ? `: ${a.detail}` : ""}
          </li>
        ))}
      </ul>
    </section>
  );
}
