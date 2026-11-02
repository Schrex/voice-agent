import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  CATEGORIES,
  editRequest,
  fetchJobs,
  type RequestDetail,
  type RequestEdit,
} from "./api";
import { useAuth } from "./App";

const NUMBER = /^\d+(\.\d+)?$/;

/**
 * Edit fields / fix the Job (spec J9): a coordinator corrects what was recorded, or assigns a
 * real Job to an Unmatched request. Only the changed fields are sent; the backend records them
 * before and after. Not offered once Resolved.
 */
export function EditFieldsAction({ request }: { request: RequestDetail }) {
  const [open, setOpen] = useState(false);
  if (!request.allowed_actions.includes("edit")) return null;
  if (!open) {
    return (
      <div className="action">
        <button type="button" onClick={() => setOpen(true)}>
          Edit fields
        </button>
      </div>
    );
  }
  return <EditForm request={request} onClose={() => setOpen(false)} />;
}

function EditForm({
  request,
  onClose,
}: {
  request: RequestDetail;
  onClose: () => void;
}) {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const jobId = request.job_id ?? null;
  const [job, setJob] = useState(jobId?.toString() ?? "");
  const [category, setCategory] = useState(request.category);
  const [need, setNeed] = useState(request.need);
  const [quantity, setQuantity] = useState(request.quantity ?? "");
  const [unit, setUnit] = useState(request.unit ?? "");
  const jobs = useQuery({
    queryKey: ["jobs", session?.accessToken],
    queryFn: () => fetchJobs(session!.accessToken),
    enabled: !!session,
  });
  const save = useMutation({
    mutationFn: (changes: RequestEdit) =>
      editRequest(session!.accessToken, request.ref, changes),
    onSuccess: (updated) => {
      queryClient.setQueryData(
        ["request", request.ref, session?.accessToken],
        updated,
      );
      void queryClient.invalidateQueries({ queryKey: ["queue"] });
      onClose();
    },
  });

  const changes: RequestEdit = {};
  if (job !== "" && Number(job) !== jobId) changes.job_id = Number(job);
  if (category !== request.category) changes.category = category;
  if (need.trim() !== request.need) changes.need = need.trim();
  const newQuantity = quantity.trim() || null;
  if (newQuantity !== request.quantity) changes.quantity = newQuantity;
  const newUnit = unit.trim() || null;
  if (newUnit !== request.unit) changes.unit = newUnit;
  const valid =
    need.trim() !== "" && (newQuantity === null || NUMBER.test(newQuantity));
  const canSave = valid && Object.keys(changes).length > 0 && !save.isPending;

  return (
    <form
      className="action edit-fields"
      aria-label="Edit fields"
      onSubmit={(e) => {
        e.preventDefault();
        if (canSave) save.mutate(changes);
      }}
    >
      <label>
        Job
        <select value={job} onChange={(e) => setJob(e.target.value)}>
          {jobId === null && (
            <option value="">Unmatched: “{request.job_spoken}”</option>
          )}
          {jobs.data?.map((j) => (
            <option key={j.id} value={j.id}>
              {j.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Category
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </label>
      <label>
        Need
        <input value={need} onChange={(e) => setNeed(e.target.value)} />
      </label>
      <label>
        Quantity
        <input
          inputMode="decimal"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
        />
      </label>
      <label>
        Unit
        <input value={unit} onChange={(e) => setUnit(e.target.value)} />
      </label>
      <button type="submit" disabled={!canSave}>
        Save
      </button>
      <button type="button" onClick={onClose}>
        Cancel
      </button>
      {jobs.isError && <p role="alert">Could not load the Jobs.</p>}
      {save.isError && <p role="alert">Could not save the changes.</p>}
    </form>
  );
}
