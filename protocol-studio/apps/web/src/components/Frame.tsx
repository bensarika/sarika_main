/**
 * App frame: wide labelled rail (left) + persistent top nav + main.
 *
 * The rail's content is page-specific (`rail` prop): the library shows its
 * sub-pages, the editor shows the 15-entry outline with completion. The
 * account menu (lower-left) is always present.
 */
import { useState, type ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useSession } from "../lib/session";

export function Frame({ rail, children }: { rail?: ReactNode; children: ReactNode }) {
  const { user, config, signOut } = useSession();
  const [menu, setMenu] = useState(false);
  const nav = useNavigate();
  const initials = (user?.name || user?.email || "?").slice(0, 2).toUpperCase();

  return (
    <div className="app">
      <aside className="rail">
        <div className="brandrow">
          <div className="logo">P</div>
          Protocol Studio
        </div>
        {rail}
        <div className="spacer" />
        <div className="me" onClick={() => setMenu((m) => !m)} role="button" tabIndex={0}>
          <div className="avatar">{initials}</div>
          <div className="label">
            <b>{user?.name || user?.email}</b>
            <small>
              {user?.role} · {config?.auth_mode === "google" ? "Google SSO" : "dev sign-in"}
            </small>
          </div>
          {menu && (
            <div className="usermenu" onClick={(e) => e.stopPropagation()}>
              <button onClick={() => nav("/library")}>My work</button>
              {user?.role === "admin" && <button onClick={() => nav("/admin")}>Admin</button>}
              <button
                onClick={async () => {
                  await signOut();
                  nav("/login");
                }}
              >
                Sign out
              </button>
            </div>
          )}
        </div>
      </aside>
      <header className="topnav">
        <NavLink to="/library" className={({ isActive }) => `nav caps ${isActive ? "active" : ""}`}>
          Library
        </NavLink>
        <NavLink to="/new" className={({ isActive }) => `nav caps ${isActive ? "active" : ""}`}>
          New protocol
        </NavLink>
        <span className="nav caps" style={{ color: "var(--slate-600)" }} title="Pilot 3">
          Calculator
        </span>
        {user?.role === "admin" && (
          <NavLink to="/admin" className={({ isActive }) => `nav caps ${isActive ? "active" : ""}`}>
            Admin
          </NavLink>
        )}
        <span className="grow" />
        <span className="env">pilot 1 · {config?.auth_mode}</span>
      </header>
      <main className="main">{children}</main>
    </div>
  );
}

/** Small reusable bits shared by pages. */
export function Chip({ kind, children }: { kind?: string; children: ReactNode }) {
  return (
    <span className={`chip ${kind ?? ""}`}>
      <i />
      {children}
    </span>
  );
}

export function Progress({ pct, drafted, width = 120 }: { pct: number; drafted?: number; width?: number }) {
  return (
    <span className="progress" title={drafted !== undefined ? `${pct}% approved · ${drafted}% drafted` : `${pct}%`}>
      <span className="bar" style={{ width }}>
        {drafted !== undefined && <em style={{ width: `${drafted}%` }} />}
        <b style={{ width: `${pct}%` }} />
      </span>
      <span className="mono">{pct}%</span>
    </span>
  );
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
