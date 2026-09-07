/** Library: every work the signed-in user can see, with completion and last activity. */
import { useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { works, type Work } from "../lib/api";
import { Chip, Frame, fmtDate } from "../components/Frame";

export function LibraryRail() {
  return (
    <>
      <div className="head caps">Library</div>
      <NavLink to="/library" end className={({ isActive }) => `item ${isActive ? "active" : ""}`}>
        <span className="t">My protocols &amp; SAPs</span>
      </NavLink>
      <NavLink to="/new" className={({ isActive }) => `item ${isActive ? "active" : ""}`}>
        <span className="t">New from starter</span>
      </NavLink>
      <div className="head caps">Pilot 2</div>
      <span className="item" style={{ opacity: 0.5 }}>
        <span className="t">Source studies</span>
      </span>
      <span className="item" style={{ opacity: 0.5 }}>
        <span className="t">Indication master sheet</span>
      </span>
      <span className="item" style={{ opacity: 0.5 }}>
        <span className="t">Conversion templates</span>
      </span>
    </>
  );
}

export function Library() {
  const [rows, setRows] = useState<Work[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const nav = useNavigate();
  useEffect(() => {
    works.list().then(setRows, (e: unknown) => setErr(String(e)));
  }, []);

  return (
    <Frame rail={<LibraryRail />}>
      <div className="page">
        <div className="row">
          <div className="grow">
            <h1>Library</h1>
            <div className="sub">Works you can view, edit or administer. Completion counts approved required slots only.</div>
          </div>
          <button className="btn primary" onClick={() => nav("/new")}>
            New protocol
          </button>
        </div>
        {err && <div className="err">{err}</div>}
        {rows && rows.length === 0 && <div className="card muted">No works yet — start one from a starter.</div>}
        {rows && rows.length > 0 && (
          <table className="grid">
            <thead>
              <tr>
                <th>ID</th>
                <th>Title</th>
                <th>Kind</th>
                <th>Indication</th>
                <th>Starter</th>
                <th className="num">Rev</th>
                <th>Updated</th>
                <th>Access</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((w) => (
                <tr key={w.id} className="click" onClick={() => nav(`/editor/${w.id}`)}>
                  <td className="mono">{w.id}</td>
                  <td>
                    <b>{w.title}</b>
                  </td>
                  <td>{w.kind}</td>
                  <td>{w.indication}</td>
                  <td className="mono">{w.starter}</td>
                  <td className="num mono">{w.revision}</td>
                  <td>{fmtDate(w.updated_at)}</td>
                  <td>
                    <Chip kind={w.my_level === "admin" ? "accent" : undefined}>{w.my_level}</Chip>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Frame>
  );
}
