import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { fetchOwners, reassignOwner, type RequestDetail } from "./api";
import { useAuth } from "./App";

const REASSIGNABLE: RequestDetail["status"][] = ["Acknowledged", "In Progress"];

/** Reassign owner (spec J9): give a request that already has an Owner another one. */
export function ReassignOwnerAction({ request }: { request: RequestDetail }) {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const [ownerId, setOwnerId] = useState("");
  const offered = REASSIGNABLE.includes(request.status);
  const owners = useQuery({
    queryKey: ["owners", session?.accessToken],
    queryFn: () => fetchOwners(session!.accessToken),
    enabled: !!session && offered,
  });
  const reassign = useMutation({
    mutationFn: (owner: number) => reassignOwner(session!.accessToken, request.ref, owner),
    onSuccess: (updated) => {
      queryClient.setQueryData(["request", request.ref, session?.accessToken], updated);
      void queryClient.invalidateQueries({ queryKey: ["queue"] });
      setOwnerId("");
    },
  });

  if (!offered) return null;
  const choices = owners.data?.filter((o) => o.id !== request.owner?.id) ?? [];
  return (
    <form
      className="action"
      aria-label="Reassign owner"
      onSubmit={(e) => {
        e.preventDefault();
        if (ownerId) reassign.mutate(Number(ownerId));
      }}
    >
      <label>
        New Owner
        <select value={ownerId} onChange={(e) => setOwnerId(e.target.value)}>
          <option value="">Choose an Owner</option>
          {choices.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </select>
      </label>
      <button type="submit" disabled={!ownerId || reassign.isPending}>
        Reassign
      </button>
      {owners.isError && <p role="alert">Could not load the Owners.</p>}
      {reassign.isError && <p role="alert">Could not reassign the Owner.</p>}
    </form>
  );
}
