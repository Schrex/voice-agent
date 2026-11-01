import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { fetchCall, fetchCallAudio, type LinkedCall, type TranscriptTurn } from "./api";
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

/** Who spoke: ElevenLabs' "user" is the Foreman. */
const SPEAKERS: Record<TranscriptTurn["role"], string> = { agent: "Agent", user: "Foreman" };

/** The request's linked calls, each with its transcript and recording (staff only). */
export function CallRecordings({ calls }: { calls: LinkedCall[] }) {
  return (
    <>
      <h2>Calls</h2>
      {calls.length === 0 && <p>No linked calls.</p>}
      {calls.map((call) => (
        <CallRecording key={`${call.id}-${call.relation}`} call={call} />
      ))}
    </>
  );
}

function CallRecording({ call }: { call: LinkedCall }) {
  const { session } = useAuth();
  const record = useQuery({
    queryKey: ["call", call.id, session?.accessToken],
    queryFn: () => fetchCall(session!.accessToken, call.id),
    enabled: !!session,
  });
  const title = `Call ${timeFormat.format(new Date(call.started_at))}`;
  const duration = record.data?.duration_s;

  return (
    <section className="call" aria-label={title}>
      <h3>{title}</h3>
      {duration != null && <p>Duration {minutes(duration)}</p>}
      <Recording callId={call.id} />
      {record.isError && <p role="alert">Could not load the transcript.</p>}
      {record.data && record.data.transcript.length === 0 && <p>No transcript yet.</p>}
      {record.data && record.data.transcript.length > 0 && (
        <ol className="transcript" aria-label="Transcript">
          {record.data.transcript.map((turn, i) => (
            <li key={i}>
              <strong>{SPEAKERS[turn.role] ?? turn.role}:</strong> {turn.message}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

type AudioState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; url: string }
  | { kind: "none" }
  | { kind: "error" };

/** Fetched only when asked: the backend streams it from ElevenLabs on each request. */
function Recording({ callId }: { callId: number }) {
  const { session } = useAuth();
  const [audio, setAudio] = useState<AudioState>({ kind: "idle" });

  useEffect(
    () => () => {
      if (audio.kind === "ready") URL.revokeObjectURL(audio.url);
    },
    [audio],
  );

  async function load() {
    if (!session) return;
    setAudio({ kind: "loading" });
    try {
      const blob = await fetchCallAudio(session.accessToken, callId);
      setAudio(blob ? { kind: "ready", url: URL.createObjectURL(blob) } : { kind: "none" });
    } catch {
      setAudio({ kind: "error" });
    }
  }

  switch (audio.kind) {
    case "ready":
      return <audio controls autoPlay src={audio.url} aria-label="Recording" />;
    case "none":
      return <p>No recording for this call.</p>;
    default:
      return (
        <>
          <button type="button" onClick={() => void load()} disabled={audio.kind === "loading"}>
            Play recording
          </button>
          {audio.kind === "error" && <p role="alert">Could not load the recording.</p>}
        </>
      );
  }
}

function minutes(seconds: number): string {
  const s = Math.round(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
