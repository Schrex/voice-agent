import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type ReactNode, type Ref } from "react";
import { Link } from "react-router-dom";

import type { Staff } from "./api";
import { useAuth } from "./App";
import { fetchQuickEntryChoices, logRequest, type Choice, type Logged } from "./quickEntryApi";

type Form = {
  foreman: string;
  job: string;
  category: string;
  need: string;
  quantity: string;
  unit: string;
  neededBy: string;
  owner: string;
};

const EMPTY: Form = {
  foreman: "",
  job: "",
  category: "",
  need: "",
  quantity: "",
  unit: "",
  neededBy: "",
  owner: "",
};

/**
 * Quick entry (spec J7): a coordinator who answered a Foreman's call logs the request. It enters
 * the queue as Recorded, or Acknowledged when an Owner is chosen. Built for the keyboard: the
 * Foreman field has focus, Tab moves on, Enter logs, and the form clears for the next call.
 */
export function QuickEntryPage({ staff }: { staff: Staff }) {
  const { auth, session } = useAuth();
  const queryClient = useQueryClient();
  const token = session!.accessToken;
  const [form, setForm] = useState<Form>(EMPTY);
  const [logged, setLogged] = useState<Logged | null>(null);
  const foremanRef = useRef<HTMLSelectElement>(null);
  const choices = useQuery({
    queryKey: ["quick-entry", token],
    queryFn: () => fetchQuickEntryChoices(token),
  });
  const log = useMutation({
    mutationFn: (f: Form) =>
      logRequest(token, {
        foreman_id: Number(f.foreman),
        job_id: Number(f.job),
        category: f.category,
        need: f.need.trim(),
        quantity: f.quantity.trim() || null,
        unit: f.unit.trim() || null,
        needed_by: f.neededBy.trim() || null,
        owner_id: f.owner ? Number(f.owner) : null,
      }),
    onSuccess: (result) => {
      setLogged(result);
      setForm(EMPTY);
      foremanRef.current?.focus();
      void queryClient.invalidateQueries({ queryKey: ["queue"] });
    },
  });
  const set = (field: keyof Form) => (value: string) => setForm((f) => ({ ...f, [field]: value }));

  return (
    <>
      <header className="topbar">
        <nav>
          <Link to="/">Queue</Link>
        </nav>
        <span>{staff.name}</span>
        <button type="button" onClick={() => void auth.signOut()}>
          Log out
        </button>
      </header>
      <main className="narrow">
        <h1>Log a request</h1>
        <p>From a call you answered. It goes into the queue like a called-in request.</p>
        {choices.isError && <p role="alert">Could not load the Foremen and Jobs.</p>}
        {choices.data && (
          <form
            className="quick-entry"
            aria-label="Log a request"
            onSubmit={(e) => {
              e.preventDefault();
              setLogged(null);
              log.mutate(form);
            }}
          >
            <Select label="Foreman" value={form.foreman} onChange={set("foreman")} selectRef={foremanRef} autoFocus required>
              {options(choices.data.foremen, "Choose a Foreman")}
            </Select>
            <Select label="Job" value={form.job} onChange={set("job")} required>
              {options(choices.data.jobs, "Choose a Job")}
            </Select>
            <Select label="Category" value={form.category} onChange={set("category")} required>
              <option value="">Choose a Category</option>
              {choices.data.categories.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </Select>
            <Text label="Need" value={form.need} onChange={set("need")} required />
            <Text label="Quantity" value={form.quantity} onChange={set("quantity")} inputMode="decimal" pattern="\d+(\.\d+)?" />
            <Text label="Unit" value={form.unit} onChange={set("unit")} />
            <Text label="Needed-by" value={form.neededBy} onChange={set("neededBy")} placeholder="e.g. tomorrow 7am" />
            <Select label="Owner (optional)" value={form.owner} onChange={set("owner")}>
              {options(choices.data.owners, "No Owner: stays Recorded")}
            </Select>
            <button type="submit" disabled={log.isPending}>
              Log request
            </button>
          </form>
        )}
        {log.isError && <p role="alert">The request was not logged. Check the fields and try again.</p>}
        {logged && (
          <p role="status">
            <Link to={`/requests/${logged.ref}`}>{logged.ref}</Link> logged: {logged.status}.
          </p>
        )}
      </main>
    </>
  );
}

function options(items: Choice[], none: string): ReactNode {
  return (
    <>
      <option value="">{none}</option>
      {items.map((item) => (
        <option key={item.id} value={item.id}>
          {item.name}
        </option>
      ))}
    </>
  );
}

function Select({
  label,
  value,
  onChange,
  children,
  selectRef,
  autoFocus,
  required,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
  selectRef?: Ref<HTMLSelectElement>;
  autoFocus?: boolean;
  required?: boolean;
}) {
  return (
    <label>
      {label}
      <select
        ref={selectRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoFocus={autoFocus}
        required={required}
      >
        {children}
      </select>
    </label>
  );
}

function Text({
  label,
  value,
  onChange,
  required,
  placeholder,
  inputMode,
  pattern,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  placeholder?: string;
  inputMode?: "decimal";
  pattern?: string;
}) {
  return (
    <label>
      {label}
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
        placeholder={placeholder}
        inputMode={inputMode}
        pattern={pattern}
      />
    </label>
  );
}
