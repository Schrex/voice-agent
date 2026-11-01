import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { OUTCOMES, resolveRequest, type Outcome, type RequestDetail } from "./api";
import { useAuth } from "./App";

/** The open statuses (Recorded, Acknowledged, In Progress): a coordinator resolves these here. */
const RESOLVABLE: RequestDetail["status"][] = ["Recorded", "Acknowledged", "In Progress"];

/**
 * Resolve (spec J9): finish an open request with an Outcome and an explanation. Neither may be
 * missing (AC9.2). A Resolved request leaves the queue.
 */
export function ResolveAction({ request }: { request: RequestDetail }) {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const [outcome, setOutcome] = useState<Outcome | "">("");
  const [explanation, setExplanation] = useState("");
  const resolve = useMutation({
    mutationFn: (body: { outcome: Outcome; explanation: string }) =>
      resolveRequest(session!.accessToken, request.ref, body.outcome, body.explanation),
    onSuccess: (updated) => {
      queryClient.setQueryData(["request", request.ref, session?.accessToken], updated);
      void queryClient.invalidateQueries({ queryKey: ["queue"] });
    },
  });

  if (!RESOLVABLE.includes(request.status)) return null;
  const ready = outcome !== "" && explanation.trim() !== "";
  return (
    <form
      className="action"
      aria-label="Resolve"
      onSubmit={(e) => {
        e.preventDefault();
        if (outcome !== "" && ready) resolve.mutate({ outcome, explanation });
      }}
    >
      <label>
        Outcome
        <select value={outcome} onChange={(e) => setOutcome(e.target.value as Outcome | "")}>
          <option value="">Choose an Outcome</option>
          {OUTCOMES.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      </label>
      <label>
        Explanation
        <textarea value={explanation} onChange={(e) => setExplanation(e.target.value)} rows={2} />
      </label>
      <button type="submit" disabled={!ready || resolve.isPending}>
        Resolve
      </button>
      {resolve.isError && <p role="alert">Could not resolve the request.</p>}
    </form>
  );
}
