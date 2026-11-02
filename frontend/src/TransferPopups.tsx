import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { dismissPopup, fetchPopups, officeTime, type Popup } from "./api";
import { useAuth } from "./App";

const REFRESH_MS = 10_000;

const TITLE: Record<Popup["kind"], string> = {
  transfer: "Incoming transfer",
  emergency: "Emergency",
};

/** Pop-ups the office must see now (AC5.3: a Foreman is being transferred), on every page. */
export function TransferPopups() {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const key = ["popups", session?.accessToken];
  const popups = useQuery({
    queryKey: key,
    queryFn: () => fetchPopups(session!.accessToken),
    enabled: !!session,
    refetchInterval: REFRESH_MS,
  });
  const dismiss = useMutation({
    mutationFn: (id: number) => dismissPopup(session!.accessToken, id),
    onSuccess: (_, id) => {
      queryClient.setQueryData<Popup[]>(key, (current) => current?.filter((p) => p.id !== id));
      void queryClient.invalidateQueries({ queryKey: key });
    },
  });
  if (!popups.data || popups.data.length === 0) return null;
  return (
    <div className="popups">
      {popups.data.map((p) => (
        <section
          key={p.id}
          role="alertdialog"
          aria-label={TITLE[p.kind]}
          className={`popup popup-${p.kind}`}
        >
          <h2>{TITLE[p.kind]}</h2>
          <p>{p.text}</p>
          <p className="popup-time">{officeTime.format(new Date(p.at))}</p>
          <button type="button" onClick={() => dismiss.mutate(p.id)} disabled={dismiss.isPending}>
            Dismiss
          </button>
          {dismiss.isError && dismiss.variables === p.id ? (
            <p role="alert">Could not dismiss. Try again.</p>
          ) : null}
        </section>
      ))}
    </div>
  );
}
