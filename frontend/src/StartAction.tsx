import { useMutation, useQueryClient } from "@tanstack/react-query";

import { startRequest, type RequestDetail } from "./api";
import { useAuth } from "./App";

/** Move to In Progress (spec J9): the Owner of an Acknowledged request is acting on it. */
export function StartAction({ request }: { request: RequestDetail }) {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const start = useMutation({
    mutationFn: () => startRequest(session!.accessToken, request.ref),
    onSuccess: (updated) => {
      queryClient.setQueryData(["request", request.ref, session?.accessToken], updated);
      void queryClient.invalidateQueries({ queryKey: ["queue"] });
    },
  });

  if (!request.allowed_actions.includes("start")) return null;
  return (
    <div className="action">
      <button type="button" onClick={() => start.mutate()} disabled={start.isPending}>
        Move to In Progress
      </button>
      {start.isError && <p role="alert">Could not move the request to In Progress.</p>}
    </div>
  );
}
