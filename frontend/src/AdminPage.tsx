import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { adminFetch, type Foreman, type Job } from "./adminApi";
import type { Staff } from "./api";
import { useAuth } from "./App";

type Write = { path: string; method: string; body?: unknown };

/** Admin: the Roster (foremen and their numbers) and the Job list (with aliases). */
export function AdminPage({ staff }: { staff: Staff }) {
  const { auth, session } = useAuth();
  const token = session!.accessToken;
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const foremen = useQuery({
    queryKey: ["admin", "foremen"],
    queryFn: () => adminFetch<Foreman[]>(token, "/foremen"),
    enabled: staff.role === "admin",
  });
  const jobs = useQuery({
    queryKey: ["admin", "jobs"],
    queryFn: () => adminFetch<Job[]>(token, "/jobs"),
    enabled: staff.role === "admin",
  });
  const write = useMutation({
    mutationFn: ({ path, method, body }: Write) => adminFetch<unknown>(token, path, method, body),
    onMutate: () => setError(null),
    onError: (e: Error) => setError(e.message),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["admin"] }),
  });
  /** Sends one change; resolves true when it was saved. */
  const save = (w: Write) =>
    write.mutateAsync(w).then(
      () => true,
      () => false,
    );

  return (
    <>
      <header className="topbar">
        <Link to="/">Queue</Link>
        <span>{staff.name}</span>
        <button type="button" onClick={() => void auth.signOut()}>
          Log out
        </button>
      </header>
      <main>
        <h1>Admin</h1>
        {staff.role !== "admin" ? (
          <p role="alert">Admins only.</p>
        ) : (
          <>
            {error && <p role="alert">{error}</p>}
            {(foremen.isError || jobs.isError) && (
              <p role="alert">Could not load the roster. Reload to try again.</p>
            )}
            <h2>Foremen</h2>
            <ForemenTable foremen={foremen.data ?? []} save={save} />
            <AddForeman save={save} />
            <h2>Jobs</h2>
            <JobsTable jobs={jobs.data ?? []} save={save} />
            <AddJob save={save} />
          </>
        )}
      </main>
    </>
  );
}

type Save = (w: Write) => Promise<boolean>;

function ForemenTable({ foremen, save }: { foremen: Foreman[]; save: Save }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Foreman</th>
          <th>Phones</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {foremen.map((f) => (
          <tr key={f.id}>
            <td>
              {f.first_name} {f.last_name}
            </td>
            <td>
              <ul className="items">
                {f.phones.map((p) => (
                  <li key={p.id}>
                    <span>{p.e164}</span>
                    <button
                      type="button"
                      aria-label={`Remove phone ${p.e164}`}
                      onClick={() =>
                        void save({ method: "DELETE", path: `/foremen/${f.id}/phones/${p.id}` })
                      }
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
              <AddOne
                label="New phone"
                button="Add phone"
                placeholder="+15855550123"
                onAdd={(e164) =>
                  save({ method: "POST", path: `/foremen/${f.id}/phones`, body: { e164 } })
                }
              />
            </td>
            <td>
              <ActiveToggle
                active={f.active}
                onToggle={() =>
                  save({ method: "PATCH", path: `/foremen/${f.id}`, body: { active: !f.active } })
                }
              />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function JobsTable({ jobs, save }: { jobs: Job[]; save: Save }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Job</th>
          <th>Aliases</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {jobs.map((j) => (
          <tr key={j.id}>
            <td>{j.name}</td>
            <td>
              <ul className="items">
                {j.aliases.map((a) => (
                  <li key={a.id}>
                    <span>{a.alias}</span>
                    <button
                      type="button"
                      aria-label={`Remove alias ${a.alias}`}
                      onClick={() =>
                        void save({ method: "DELETE", path: `/jobs/${j.id}/aliases/${a.id}` })
                      }
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
              <AddOne
                label="New alias"
                button="Add alias"
                onAdd={(alias) =>
                  save({ method: "POST", path: `/jobs/${j.id}/aliases`, body: { alias } })
                }
              />
            </td>
            <td>
              <ActiveToggle
                active={j.active}
                onToggle={() =>
                  save({ method: "PATCH", path: `/jobs/${j.id}`, body: { active: !j.active } })
                }
              />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ActiveToggle({ active, onToggle }: { active: boolean; onToggle: () => void }) {
  return (
    <span className="inline">
      <span>{active ? "Active" : "Inactive"}</span>
      <button type="button" onClick={onToggle}>
        {active ? "Deactivate" : "Reactivate"}
      </button>
    </span>
  );
}

/** One text box and a button, cleared after the value is saved. */
function AddOne(props: {
  label: string;
  button: string;
  placeholder?: string;
  onAdd: (value: string) => Promise<boolean>;
}) {
  const [value, setValue] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (await props.onAdd(value.trim())) setValue("");
  }
  return (
    <form className="inline" onSubmit={submit}>
      <input
        aria-label={props.label}
        placeholder={props.placeholder}
        required
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
      <button type="submit">{props.button}</button>
    </form>
  );
}

function AddForeman({ save }: { save: Save }) {
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [phone, setPhone] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    const phones = phone.trim() ? [phone.trim()] : [];
    const body = { first_name: first.trim(), last_name: last.trim(), phones };
    if (await save({ method: "POST", path: "/foremen", body })) {
      setFirst("");
      setLast("");
      setPhone("");
    }
  }
  return (
    <form aria-label="Add foreman" className="add" onSubmit={submit}>
      <label>
        First name
        <input required value={first} onChange={(e) => setFirst(e.target.value)} />
      </label>
      <label>
        Last name
        <input required value={last} onChange={(e) => setLast(e.target.value)} />
      </label>
      <label>
        Phone
        <input
          placeholder="+15855550123"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
        />
      </label>
      <button type="submit">Add foreman</button>
    </form>
  );
}

function AddJob({ save }: { save: Save }) {
  const [name, setName] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (await save({ method: "POST", path: "/jobs", body: { name: name.trim(), aliases: [] } })) {
      setName("");
    }
  }
  return (
    <form aria-label="Add job" className="add" onSubmit={submit}>
      <label>
        Job name
        <input required value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <button type="submit">Add job</button>
    </form>
  );
}
