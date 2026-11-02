import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { addNote, type RequestDetail } from "./api";
import { useAuth } from "./App";

/** Add note (spec J9): a coordinator appends a note; it changes no field and texts nobody. */
export function AddNoteAction({ request }: { request: RequestDetail }) {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const add = useMutation({
    mutationFn: (note: string) => addNote(session!.accessToken, request.ref, note),
    onSuccess: (updated) => {
      queryClient.setQueryData(["request", request.ref, session?.accessToken], updated);
      setText("");
    },
  });

  if (!request.allowed_actions.includes("note")) return null;
  const ready = text.trim() !== "";
  return (
    <form
      className="action"
      aria-label="Add note"
      onSubmit={(e) => {
        e.preventDefault();
        if (ready) add.mutate(text);
      }}
    >
      <label>
        Note
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} />
      </label>
      <button type="submit" disabled={!ready || add.isPending}>
        Add note
      </button>
      {add.isError && <p role="alert">Could not add the note.</p>}
    </form>
  );
}
