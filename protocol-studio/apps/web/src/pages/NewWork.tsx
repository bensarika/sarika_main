/**
 * New work wizard (Pilot 1 subset of docs/04_workflows.md §2).
 *
 * Step 1 pick a starter (blank or a library example) → step 2 name it →
 * create. Intelligent drug substitution and the conversion-question list are
 * Pilot 2 (they need the ingestion pipeline), so this wizard is deliberately short.
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { library, works, type Starter } from "../lib/api";
import { Chip, Frame } from "../components/Frame";
import { LibraryRail } from "./Library";

export function NewWork() {
  const [starters, setStarters] = useState<Starter[]>([]);
  const [sel, setSel] = useState<string>("blank");
  const [title, setTitle] = useState("");
  const [indication, setIndication] = useState("atopic dermatitis");
  const [kind, setKind] = useState<"protocol" | "sap">("protocol");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const nav = useNavigate();

  useEffect(() => {
    library.starters().then(setStarters, (e: unknown) => setErr(String(e)));
  }, []);

  const chosen = starters.find((s) => s.id === sel);

  async function create() {
    setBusy(true);
    setErr(null);
    try {
      const w = await works.create({ title: title.trim(), indication, kind, starter: sel });
      nav(`/editor/${w.id}`);
    } catch (e) {
      setErr(String(e));
      setBusy(false);
    }
  }

  return (
    <Frame rail={<LibraryRail />}>
      <div className="page">
        <h1>New protocol</h1>
        <div className="sub">Pick a starting point. Everything copied from a starter is marked “imported” until you approve it.</div>

        <div className="card">
          <h2 className="caps">1 · Starter</h2>
          <div className="starters">
            {starters.map((s) => (
              <button key={s.id} className={`starter ${sel === s.id ? "sel" : ""}`} onClick={() => setSel(s.id)}>
                <div className="row">
                  <b className="grow">{s.title}</b>
                  <Chip kind={s.kind === "blank" ? undefined : "imported"}>{s.kind.replace("_", " ")}</Chip>
                </div>
                <span className="muted tiny">{s.description}</span>
                {s.indication && <span className="tiny">{s.indication}</span>}
              </button>
            ))}
          </div>
        </div>

        <div className="card">
          <h2 className="caps">2 · Identity</h2>
          <div className="row" style={{ gap: 16, alignItems: "flex-end", flexWrap: "wrap" }}>
            <label className="field grow">
              <span>Working title</span>
              <input className="text" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. SRK-201 Phase 2b in moderate-to-severe AD" />
            </label>
            <label className="field">
              <span>Indication</span>
              <input className="text" value={indication} onChange={(e) => setIndication(e.target.value)} />
            </label>
            <label className="field">
              <span>Document</span>
              <select className="text" value={kind} onChange={(e) => setKind(e.target.value as "protocol" | "sap")}>
                <option value="protocol">Protocol</option>
                <option value="sap">SAP</option>
              </select>
            </label>
          </div>
          {chosen && chosen.id !== "blank" && (
            <p className="muted tiny" style={{ marginTop: 10 }}>
              Starting from <b>{chosen.title}</b>. The source drug is not renamed automatically in Pilot 1; the
              conversion wizard (intelligent substitution + question list) arrives with ingestion in Pilot 2.
            </p>
          )}
          {err && <div className="err">{err}</div>}
          <div className="row" style={{ marginTop: 12 }}>
            <span className="grow" />
            <button className="btn primary" disabled={busy || !title.trim()} onClick={create}>
              {busy ? "Creating…" : "Create and open editor"}
            </button>
          </div>
        </div>
      </div>
    </Frame>
  );
}
