/**
 * Admin portal: users & roles · usage · audit log. Models & providers and
 * per-work permissions matrix arrive with Pilot 3 / the model layer.
 */
import { useEffect, useState } from "react";
import { NavLink, useParams } from "react-router-dom";
import { admin, type AdminUser, type AuditRow, type UsageRow } from "../lib/api";
import { Chip, Frame, fmtDate } from "../components/Frame";

const TABS = [
  ["users", "Users & roles"],
  ["usage", "Usage"],
  ["audit", "Audit log"],
] as const;
type Tab = (typeof TABS)[number][0];

export function Admin() {
  const { tab = "users" } = useParams<{ tab: Tab }>();
  const rail = (
    <>
      <div className="head caps">Admin</div>
      {TABS.map(([id, label]) => (
        <NavLink key={id} to={`/admin/${id}`} className={({ isActive }) => `item ${isActive || (id === "users" && tab === "users") ? "active" : ""}`}>
          <span className="t">{label}</span>
        </NavLink>
      ))}
      <div className="head caps">Later pilots</div>
      <span className="item" style={{ opacity: 0.5 }}>
        <span className="t">Models &amp; providers</span>
      </span>
      <span className="item" style={{ opacity: 0.5 }}>
        <span className="t">Work permissions matrix</span>
      </span>
    </>
  );
  return (
    <Frame rail={rail}>
      <div className="page">
        {tab === "users" && <Users />}
        {tab === "usage" && <Usage />}
        {tab === "audit" && <Audit />}
      </div>
    </Frame>
  );
}

function Users() {
  const [rows, setRows] = useState<AdminUser[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("author");
  const [err, setErr] = useState<string | null>(null);
  const load = () => admin.users().then(setRows, (e: unknown) => setErr(String(e)));
  useEffect(() => {
    void load();
  }, []);
  return (
    <>
      <h1>Users &amp; roles</h1>
      <div className="sub">Only active users may sign in. Roles: admin (everything), author (create/edit), reviewer (view + adjudicate).</div>
      <div className="card row" style={{ marginBottom: 12 }}>
        <input className="text grow" placeholder="name@sarika.com" value={email} onChange={(e) => setEmail(e.target.value)} />
        <select className="text" value={role} onChange={(e) => setRole(e.target.value)}>
          <option>author</option>
          <option>reviewer</option>
          <option>admin</option>
        </select>
        <button
          className="btn primary"
          disabled={!email.includes("@")}
          onClick={async () => {
            setErr(null);
            try {
              await admin.addUser({ email: email.trim().toLowerCase(), role });
              setEmail("");
              await load();
            } catch (e) {
              setErr(String(e));
            }
          }}
        >
          Authorise
        </button>
      </div>
      {err && <div className="err">{err}</div>}
      <table className="grid">
        <thead>
          <tr>
            <th>Email</th>
            <th>Name</th>
            <th>Role</th>
            <th>Status</th>
            <th>Last seen</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((u) => (
            <tr key={u.id}>
              <td>{u.email}</td>
              <td>{u.name}</td>
              <td>
                <select className="text" style={{ height: 26 }} value={u.role} onChange={async (e) => (await admin.patchUser(u.id, { role: e.target.value }), load())}>
                  <option>admin</option>
                  <option>author</option>
                  <option>reviewer</option>
                </select>
              </td>
              <td>
                <Chip kind={u.active ? "ok" : "error"}>{u.active ? "active" : "disabled"}</Chip>
              </td>
              <td>{fmtDate(u.last_seen_at)}</td>
              <td>
                <button className="btn sm" onClick={async () => (await admin.patchUser(u.id, { active: !u.active }), load())}>
                  {u.active ? "Disable" : "Enable"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function Usage() {
  const [rows, setRows] = useState<UsageRow[]>([]);
  useEffect(() => {
    admin.usage().then(setRows, () => setRows([]));
  }, []);
  return (
    <>
      <h1>Usage</h1>
      <div className="sub">Counted from the audit log. Model-call usage and cost land here once the provider layer ships.</div>
      <table className="grid">
        <thead>
          <tr>
            <th>User</th>
            <th className="num">Logins</th>
            <th className="num">Edits</th>
            <th className="num">Exports</th>
            <th className="num">Freezes</th>
            <th className="num">Other</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.email}>
              <td>{r.email}</td>
              <td className="num">{r.logins}</td>
              <td className="num">{r.commands}</td>
              <td className="num">{r.exports}</td>
              <td className="num">{r.freezes}</td>
              <td className="num">{r.other}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function Audit() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  useEffect(() => {
    admin.audit().then(setRows, () => setRows([]));
  }, []);
  return (
    <>
      <h1>Audit log</h1>
      <div className="sub">Every login, command, export and freeze, newest first.</div>
      <table className="grid">
        <thead>
          <tr>
            <th>When</th>
            <th>Actor</th>
            <th>Action</th>
            <th>Work</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{fmtDate(r.at)}</td>
              <td>{r.actor ?? "—"}</td>
              <td className="mono">{r.action}</td>
              <td className="mono">{r.work_id ?? ""}</td>
              <td className="mono muted">{JSON.stringify(r.detail)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
