import { useMutation, useQueryClient } from "@tanstack/react-query";

import { markForemanInformed, officeTime, type RequestDetail } from "./api";
import { useAuth } from "./App";

/**
 * Foreman Informed (spec §5, J9): on a Resolved request, whether a person has told the Foreman
 * the Outcome, the Uninformed flag when nobody has within the threshold (AC9.4), and the
 * "Mark Foreman Informed" action. Dashboard only: nothing is sent to the Foreman (ADR 0002).
 */
export function ForemanInformedAction({ request }: { request: RequestDetail }) {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const mark = useMutation({
    mutationFn: () => markForemanInformed(session!.accessToken, request.ref),
    onSuccess: (updated) => {
      queryClient.setQueryData(["request", request.ref, session?.accessToken], updated);
      void queryClient.invalidateQueries({ queryKey: ["uninformed"] });
    },
  });

  const markable = request.allowed_actions.includes("mark_informed");
  if (!markable && !request.foreman_informed_at) return null;
  return (
    <section className="action" aria-labelledby="foreman-informed">
      <h2 id="foreman-informed">Foreman Informed</h2>
      {request.foreman_informed_at ? (
        <p>Foreman Informed {officeTime.format(new Date(request.foreman_informed_at))}</p>
      ) : (
        <>
          <p>
            {request.uninformed && <span className="flag">Uninformed</span>} Not marked Foreman
            Informed
          </p>
          <button type="button" onClick={() => mark.mutate()} disabled={mark.isPending}>
            Mark Foreman Informed
          </button>
          {mark.isError && <p role="alert">Could not mark the request Foreman Informed.</p>}
        </>
      )}
    </section>
  );
}
