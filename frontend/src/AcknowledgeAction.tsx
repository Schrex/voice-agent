import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { acknowledgeRequest, fetchOwners, type RequestDetail } from "./api";
import { useAuth } from "./App";

/**
 * Acknowledge (spec J9): a coordinator accepts a Recorded request by choosing its Owner,
 * prefilled with the category's default. No Owner, no Acknowledge (AC9.1).
 */
export function AcknowledgeAction({ request }: { request: RequestDetail }) {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const [ownerId, setOwnerId] = useState(request.default_owner_id?.toString() ?? "");
  const owners = useQuery({
    queryKey: ["owners", session?.accessToken],
    queryFn: () => fetchOwners(session!.accessToken),
    enabled: !!session && request.status === "Recorded",
  });
  const acknowledge = useMutation({
    mutationFn: (owner: number) => acknowledgeRequest(session!.accessToken, request.ref, owner),
    onSuccess: (updated) => {
      queryClient.setQueryData(["request", request.ref, session?.accessToken], updated);
      void queryClient.invalidateQueries({ queryKey: ["queue"] });
    },
  });

  if (request.status !== "Recorded") return null;
  return (
    <form
      className="action"
      aria-label="Acknowledge"
      onSubmit={(e) => {
        e.preventDefault();
        if (ownerId) acknowledge.mutate(Number(ownerId));
      }}
    >
      <label>
        Owner
        <select value={ownerId} onChange={(e) => setOwnerId(e.target.value)}>
          <option value="">Choose an Owner</option>
          {owners.data?.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </select>
      </label>
      <button type="submit" disabled={!ownerId || acknowledge.isPending}>
        Acknowledge
      </button>
      {owners.isError && <p role="alert">Could not load the Owners.</p>}
      {acknowledge.isError && <p role="alert">Could not acknowledge the request.</p>}
    </form>
  );
}
