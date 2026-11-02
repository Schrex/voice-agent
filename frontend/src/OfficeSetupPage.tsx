import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import {
  adminFetch,
  type CategoryDefault,
  type DutyDay,
  type OfficeSettings,
  type Owner,
  type StaffMember,
} from "./adminApi";
import type { Staff } from "./api";
import { useAuth } from "./App";

type Write = { path: string; method: string; body?: unknown };
type Save = (w: Write) => Promise<boolean>;

/** A New York calendar date ("2026-11-02") as "Mon, Nov 2, 2026"; no time zone shift. */
const dayFormat = new Intl.DateTimeFormat("en-US", {
  weekday: "short",
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});
const showDay = (iso: string) => dayFormat.format(new Date(`${iso}T00:00:00Z`));

/** Admin: Owners and category defaults, staff, the duty roster and office settings (#35). */
export function OfficeSetupPage({ staff }: { staff: Staff }) {
  const { auth, session } = useAuth();
  const token = session!.accessToken;
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const get = <T,>(path: string) => ({
    queryKey: ["admin", path],
    queryFn: () => adminFetch<T>(token, path),
  });
  const duty = useQuery(get<DutyDay[]>("/duty"));
  const staffList = useQuery(get<StaffMember[]>("/staff"));
  const owners = useQuery(get<Owner[]>("/owners"));
  const defaults = useQuery(get<CategoryDefault[]>("/category-defaults"));
  const settings = useQuery(get<OfficeSettings>("/settings"));

  const write = useMutation({
    mutationFn: ({ path, method, body }: Write) =>
      adminFetch<unknown>(token, path, method, body),
    onMutate: () => setError(null),
    onError: (e: Error) => setError(e.message),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["admin"] }),
  });
  const save: Save = (w) =>
    write.mutateAsync(w).then(
      () => true,
      () => false,
    );
  const loadFailed = [duty, staffList, owners, defaults, settings].some(
    (q) => q.isError,
  );

  return (
    <>
      <header className="topbar">
        <Link to="/">Queue</Link>
        <Link to="/admin">Admin</Link>
        <span>{staff.name}</span>
        <button type="button" onClick={() => void auth.signOut()}>
          Log out
        </button>
      </header>
      <main>
        <h1>Owners, staff, duty roster, settings</h1>
        {error && <p role="alert">{error}</p>}
        {loadFailed && (
          <p role="alert">
            Could not load the office setup. Reload to try again.
          </p>
        )}
        <h2>Duty roster</h2>
        <DutyTable days={duty.data ?? []} save={save} />
        <SetDutyDay staff={staffList.data ?? []} save={save} />
        <h2>Staff</h2>
        <StaffTable staff={staffList.data ?? []} save={save} />
        <AddStaff save={save} />
        <h2>Owners</h2>
        <OwnersTable owners={owners.data ?? []} />
        <AddOwner save={save} />
        <h2>Category defaults</h2>
        <DefaultsTable
          defaults={defaults.data ?? []}
          owners={owners.data ?? []}
          save={save}
        />
        <h2>Settings</h2>
        {settings.data && (
          <SettingsForm current={settings.data} save={save} />
        )}
      </main>
    </>
  );
}

function DutyTable({ days, save }: { days: DutyDay[]; save: Save }) {
  if (days.length === 0) return <p>No duty days set.</p>;
  return (
    <table>
      <thead>
        <tr>
          <th>Date</th>
          <th>On duty</th>
          <th>Backup</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {days.map((d) => (
          <tr key={d.date}>
            <td>{showDay(d.date)}</td>
            <td>{d.on_duty.name}</td>
            <td>{d.backup?.name ?? "—"}</td>
            <td>
              <button
                type="button"
                onClick={() =>
                  void save({ method: "DELETE", path: `/duty/${d.date}` })
                }
              >
                Remove
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function SetDutyDay({ staff, save }: { staff: StaffMember[]; save: Save }) {
  const [date, setDate] = useState("");
  const [onDuty, setOnDuty] = useState("");
  const [backup, setBackup] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    const body = { on_duty_staff_id: onDuty, backup_staff_id: backup || null };
    if (await save({ method: "PUT", path: `/duty/${date}`, body })) {
      setDate("");
      setOnDuty("");
      setBackup("");
    }
  }
  return (
    <form aria-label="Set duty day" className="add" onSubmit={submit}>
      <label>
        Date
        <input
          type="date"
          required
          value={date}
          onChange={(e) => setDate(e.target.value)}
        />
      </label>
      <label>
        On duty
        <select
          required
          value={onDuty}
          onChange={(e) => setOnDuty(e.target.value)}
        >
          <option value="">Choose…</option>
          {staff.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Backup
        <select value={backup} onChange={(e) => setBackup(e.target.value)}>
          <option value="">None</option>
          {staff.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </label>
      <button type="submit">Save duty day</button>
    </form>
  );
}

function StaffTable({ staff, save }: { staff: StaffMember[]; save: Save }) {
  // The person whose removal waits for a second click; one at a time.
  const [confirming, setConfirming] = useState<string | null>(null);
  return (
    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>Email</th>
          <th>Phone</th>
          <th>Access</th>
        </tr>
      </thead>
      <tbody>
        {staff.map((s) => (
          <tr key={s.id}>
            <td>{s.name}</td>
            <td>{s.email}</td>
            <td>{s.phone_e164 ?? "—"}</td>
            <td>
              {confirming === s.id ? (
                <span className="inline">
                  <span>Remove {s.name}? They lose access at once.</span>
                  <button
                    type="button"
                    onClick={() =>
                      void save({ method: "DELETE", path: `/staff/${s.id}` }).then(() =>
                        setConfirming(null),
                      )
                    }
                  >
                    Yes, remove
                  </button>
                  <button type="button" onClick={() => setConfirming(null)}>
                    Cancel
                  </button>
                </span>
              ) : (
                <button type="button" onClick={() => setConfirming(s.id)}>
                  Remove
                </button>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function AddStaff({ save }: { save: Save }) {
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    const body = {
      id: id.trim(),
      name: name.trim(),
      email: email.trim(),
      phone_e164: phone.trim() || null,
    };
    if (await save({ method: "POST", path: "/staff", body })) {
      setId("");
      setName("");
      setEmail("");
      setPhone("");
    }
  }
  return (
    <form aria-label="Add staff" className="add" onSubmit={submit}>
      <label>
        Supabase user id
        <input required value={id} onChange={(e) => setId(e.target.value)} />
      </label>
      <label>
        Name
        <input
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <label>
        Email
        <input
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </label>
      <label>
        Phone
        <input
          placeholder="+15855550123"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
        />
      </label>
      <button type="submit">Add staff</button>
    </form>
  );
}

function OwnersTable({ owners }: { owners: Owner[] }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Owner</th>
          <th>Phone</th>
          <th>Email</th>
        </tr>
      </thead>
      <tbody>
        {owners.map((o) => (
          <tr key={o.id}>
            <td>{o.name}</td>
            <td>{o.phone_e164 ?? "—"}</td>
            <td>{o.email ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function AddOwner({ save }: { save: Save }) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    const body = {
      name: name.trim(),
      phone_e164: phone.trim() || null,
      email: email.trim() || null,
    };
    if (await save({ method: "POST", path: "/owners", body })) {
      setName("");
      setPhone("");
      setEmail("");
    }
  }
  return (
    <form aria-label="Add owner" className="add" onSubmit={submit}>
      <label>
        Owner name
        <input
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <label>
        Owner phone
        <input
          placeholder="+15855550123"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
        />
      </label>
      <label>
        Owner email
        <input value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <button type="submit">Add owner</button>
    </form>
  );
}

function DefaultsTable(props: {
  defaults: CategoryDefault[];
  owners: Owner[];
  save: Save;
}) {
  return (
    <table>
      <thead>
        <tr>
          <th>Category</th>
          <th>Default owner</th>
        </tr>
      </thead>
      <tbody>
        {props.defaults.map((d) => (
          <tr key={d.category}>
            <td>{d.category}</td>
            <td>
              <select
                aria-label={`Default owner for ${d.category}`}
                value={d.owner_id ?? ""}
                onChange={(e) =>
                  void props.save({
                    method: "PUT",
                    path: `/category-defaults/${encodeURIComponent(d.category)}`,
                    body: {
                      owner_id: e.target.value ? Number(e.target.value) : null,
                    },
                  })
                }
              >
                <option value="">None</option>
                {props.owners.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Starts from the settings as first loaded; after a save the fields already show them. */
function SettingsForm({
  current,
  save,
}: {
  current: OfficeSettings;
  save: Save;
}) {
  const [officeLine, setOfficeLine] = useState(current.office_line_e164 ?? "");
  const [today, setToday] = useState(String(current.ack_window_today_min));
  const [planned, setPlanned] = useState(
    String(current.ack_window_planned_min),
  );
  const [saved, setSaved] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaved(false);
    const body = {
      office_line_e164: officeLine.trim() || null,
      ack_window_today_min: Number(today),
      ack_window_planned_min: Number(planned),
    };
    setSaved(await save({ method: "PATCH", path: "/settings", body }));
  }
  return (
    <form aria-label="Settings" className="add" onSubmit={submit}>
      <label>
        Office line
        <input
          placeholder="+15855550100"
          value={officeLine}
          onChange={(e) => setOfficeLine(e.target.value)}
        />
      </label>
      <label>
        Today ack window (minutes)
        <input
          type="number"
          required
          value={today}
          onChange={(e) => setToday(e.target.value)}
        />
      </label>
      <label>
        Planned ack window (minutes)
        <input
          type="number"
          required
          value={planned}
          onChange={(e) => setPlanned(e.target.value)}
        />
      </label>
      <button type="submit">Save settings</button>
      {saved && <p>Settings saved.</p>}
    </form>
  );
}
