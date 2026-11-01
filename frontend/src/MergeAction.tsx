import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { mergeRequest, OUTCOMES, type Outcome, type RequestDetail } from "./api";
import { useAuth } from "./App";

/** Open statuses; the same ones Resolve is offered on, since merging resolves this request. */
const MERGEABLE: RequestDetail["status"][] = ["Recorded", "Acknowledged", "In Progress"];

/**
 * Merge duplicates (spec J2, J9): this request is Resolved, with an Outcome and explanation, and
 * points to the request it was merged into. The backend refuses merging into itself or into a
 * Resolved request.
 */
export function MergeAction({ request }: { request: RequestDetail }) {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [into, setInto] = useState("");
  const [outcome, setOutcome] = useState<Outcome | "">("");
  const [explanation, setExplanation] = useState("");
  const merge = useMutation({
    mutationFn: (body: { into: string; outcome: Outcome; explanation: string }) =>
      mergeRequest(session!.accessToken, request.ref, body.into, body.outcome, body.explanation),
    onSuccess: (updated) => {
      queryClient.setQueryData(["request", request.ref, session?.accessToken], updated);
      void queryClient.invalidateQueries({ queryKey: ["queue"] });
      void queryClient.invalidateQueries({ queryKey: ["request", updated.merged_into] });
    },
  });

  if (!MERGEABLE.includes(request.status)) return null;
  if (!open) {
    return (
      <p className="action">
        <button type="button" onClick={() => setOpen(true)}>
          Merge into another request
        </button>
      </p>
    );
  }
  const target = into.trim();
  const ready = target !== "" && outcome !== "" && explanation.trim() !== "";
  return (
    <form
      className="action"
      aria-label="Merge"
      onSubmit={(e) => {
        e.preventDefault();
        if (ready) merge.mutate({ into: target, outcome, explanation });
      }}
    >
      <label>
        Merge into
        <input value={into} onChange={(e) => setInto(e.target.value)} placeholder="R-1042" />
      </label>
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
      <button type="submit" disabled={!ready || merge.isPending}>
        Merge
      </button>
      {merge.isError && <p role="alert">Could not merge the request.</p>}
    </form>
  );
}
