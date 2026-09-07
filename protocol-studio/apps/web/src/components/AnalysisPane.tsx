/**
 * Right-hand analysis pane for the editor: FINDINGS · MODEL · HISTORY.
 *
 * - FINDINGS lists deterministic rule findings for the current section (or all),
 *   with accept/dismiss for those flagged `needs_adjudication`.
 * - MODEL shows what remains for the section (required slots) and lets the
 *   author set scalar fields or mark a slot "not applicable" with a reason.
 * - HISTORY shows the revision log, frozen versions, freeze + export actions.
 */
import { useEffect, useState } from "react";
import { works, type Evaluation, type Finding, type RevisionEntry, type SectionCompletion, type Slot, type Version } from "../lib/api";
import type { Cmd, DraftSession } from "../lib/useDraft";
import { parseLoose } from "./BlockEditor";
import { Chip, fmtDate, Progress } from "./Frame";

type Tab = "findings" | "model" | "history";

export function AnalysisPane({ session, sectionId, canEdit }: { session: DraftSession; sectionId: string; canEdit: boolean }) {
  const [tab, setTab] = useState<Tab>("findings");
  const ev = session.evaluation;
  const sec = ev?.completion.sections.find((s) => s.section_id === sectionId) ?? null;
  const sectionFindings = ev?.findings.filter((f) => f.section_id === sectionId) ?? [];

  return (
    <aside className="pane">
      <div className="tabs caps">
        <button className={tab === "findings" ? "active" : ""} onClick={() => setTab("findings")}>
          Findings {ev ? `(${sectionFindings.length})` : ""}
        </button>
        <button className={tab === "model" ? "active" : ""} onClick={() => setTab("model")}>
          Model {sec ? `(${sec.remaining.length})` : ""}
        </button>
        <button className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}>
          History
        </button>
      </div>
      <div className="body">
        {tab === "findings" && ev && <Findings ev={ev} own={sectionFindings} session={session} canEdit={canEdit} />}
        {tab === "model" && sec && <ModelTab sec={sec} model={session.state?.model ?? {}} na={session.state?.not_applicable ?? {}} send={session.send} canEdit={canEdit} />}
        {tab === "history" && <History session={session} canEdit={canEdit} />}
      </div>
    </aside>
  );
}

// ----------------------------------------------------------------------------- findings

function Findings({ ev, own, session, canEdit }: { ev: Evaluation; own: Finding[]; session: DraftSession; canEdit: boolean }) {
  const [all, setAll] = useState(false);
  const list = all ? ev.findings : own;
  const workId = session.work?.id ?? "";
  return (
    <>
      <div className="row" style={{ marginBottom: 10, flexWrap: "wrap" }}>
        {Object.entries(ev.counts).map(([k, n]) => (
          <Chip key={k} kind={k}>
            {n} {k}
          </Chip>
        ))}
        <span className="grow" />
        <label className="tiny row">
          <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> all sections
        </label>
      </div>
      <div className="card" style={{ marginBottom: 10 }}>
        <div className="row">
          <b>Formal review</b>
          <span className="grow" />
          <Chip kind={ev.readiness.ready ? "ok" : "warning"}>{ev.readiness.ready ? "ready" : "not ready"}</Chip>
        </div>
        {ev.readiness.blockers.map((b) => (
          <div key={b} className="tiny muted">
            · {b}
          </div>
        ))}
      </div>
      {list.length === 0 && <div className="muted">No findings{all ? "" : " in this section"}. Deterministic checks are current at revision {ev.revision}.</div>}
      {list.map((f) => (
        <div key={f.key} className={`finding ${f.severity}`}>
          <div className="row">
            <Chip kind={f.severity}>{f.severity}</Chip>
            <span className="mono">{f.rule_id}</span>
            {f.adjudication && <Chip kind={f.adjudication === "accepted" ? "ok" : undefined}>{f.adjudication}</Chip>}
            <span className="grow" />
            {all && f.section_id && <span className="tiny muted">{f.section_id.replace("section.", "§")}</span>}
          </div>
          <div className="msg">{f.message}</div>
          {f.explanation && <div className="tiny muted">{f.explanation}</div>}
          {f.targets.map((t) => (
            <div key={t} className="path">
              {t}
            </div>
          ))}
          {f.suggested_fix && <div className="tiny">Fix: {f.suggested_fix}</div>}
          {canEdit && f.needs_adjudication && !f.adjudication && (
            <div className="row" style={{ marginTop: 6 }}>
              {(["accepted", "dismissed"] as const).map((d) => (
                <button
                  key={d}
                  className="btn sm"
                  onClick={async () => {
                    await works.adjudicate(workId, { finding_key: f.key, decision: d, revision: f.revision });
                    await session.reload();
                  }}
                >
                  {d === "accepted" ? "Accept (real issue)" : "Dismiss"}
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
    </>
  );
}

// ----------------------------------------------------------------------------- model / slots

const INTENTS = ["exploratory", "confirmatory", "mixed", "other"];

function ModelTab({
  sec,
  model,
  na,
  send,
  canEdit,
}: {
  sec: SectionCompletion;
  model: Record<string, unknown>;
  na: Record<string, string>;
  send: (c: Cmd) => Promise<boolean>;
  canEdit: boolean;
}) {
  const [showJson, setShowJson] = useState(false);
  const naHere = Object.keys(na).filter((k) => k.startsWith(sec.section_id.replace("section.", "s") + "."));
  return (
    <>
      <div className="row" style={{ marginBottom: 10 }}>
        <Progress pct={sec.pct} drafted={sec.drafted_pct} width={140} />
        <span className="tiny muted">
          {sec.filled}/{sec.applicable} required slots
        </span>
      </div>
      {sec.remaining.length === 0 && <div className="muted">Every required slot in this section is filled.</div>}
      {sec.remaining.map((s) => (
        <SlotRow key={s.id} slot={s} send={send} canEdit={canEdit} />
      ))}
      {naHere.length > 0 && (
        <div className="card" style={{ marginTop: 10 }}>
          <h2 className="caps">Reviewed not applicable</h2>
          {naHere.map((k) => (
            <div key={k} className="row tiny">
              <span className="mono grow">{k}</span>
              <span className="muted">{na[k]}</span>
              {canEdit && (
                <button className="btn sm ghost" onClick={() => void send({ type: "set_not_applicable", slot_id: k, reason: null })}>
                  undo
                </button>
              )}
            </div>
          ))}
        </div>
      )}
      <div style={{ marginTop: 14 }}>
        <button className="btn sm ghost" onClick={() => setShowJson((v) => !v)}>
          {showJson ? "Hide" : "Show"} trial model JSON
        </button>
        {showJson && (
          <pre className="mono" style={{ whiteSpace: "pre-wrap", background: "var(--slate-50)", padding: 8, borderRadius: 6, maxHeight: 420, overflow: "auto" }}>
            {JSON.stringify(model, null, 2)}
          </pre>
        )}
      </div>
    </>
  );
}

/** One unfilled slot: inline value entry for scalar fields, plus "not applicable". */
function SlotRow({ slot, send, canEdit }: { slot: Slot; send: (c: Cmd) => Promise<boolean>; canEdit: boolean }) {
  const [v, setV] = useState("");
  const [naReason, setNaReason] = useState<string | null>(null);
  const scalar = (slot.kind === "field" || slot.kind === "entity_field") && slot.target_path && !slot.target_path.endsWith("study_identifiers");
  const isIntent = slot.target_path?.endsWith(".intent");
  return (
    <div className="finding incomplete">
      <div className="row">
        <span className="grow">{slot.label}</span>
        {slot.rule_id && <span className="mono muted">{slot.rule_id}</span>}
      </div>
      {slot.target_path && <div className="path">{slot.target_path}</div>}
      {canEdit && (
        <div className="row" style={{ marginTop: 6, flexWrap: "wrap" }}>
          {scalar && !isIntent && <input className="text" style={{ height: 26, flex: 1 }} placeholder="value" value={v} onChange={(e) => setV(e.target.value)} />}
          {scalar && isIntent && (
            <select className="text" style={{ height: 26 }} value={v} onChange={(e) => setV(e.target.value)}>
              <option value="">choose…</option>
              {INTENTS.map((i) => (
                <option key={i}>{i}</option>
              ))}
            </select>
          )}
          {scalar && (
            <button className="btn sm primary" disabled={!v} onClick={() => void send({ type: "set_field", path: slot.target_path!, value: parseLoose(v) })}>
              Set
            </button>
          )}
          {slot.target_path?.endsWith("study_identifiers") && (
            <IdentifierAdder send={send} />
          )}
          {naReason === null ? (
            <button className="btn sm ghost" onClick={() => setNaReason("")}>
              Not applicable…
            </button>
          ) : (
            <>
              <input className="text" style={{ height: 26, flex: 1 }} placeholder="why it does not apply" value={naReason} onChange={(e) => setNaReason(e.target.value)} />
              <button className="btn sm" disabled={!naReason.trim()} onClick={() => void send({ type: "set_not_applicable", slot_id: slot.id, reason: `reviewed: ${naReason.trim()}` })}>
                Confirm
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function IdentifierAdder({ send }: { send: (c: Cmd) => Promise<boolean> }) {
  const [system, setSystem] = useState("sponsor");
  const [value, setValue] = useState("");
  return (
    <>
      <input className="text" style={{ height: 26, width: 90 }} value={system} onChange={(e) => setSystem(e.target.value)} placeholder="system" />
      <input className="text" style={{ height: 26, flex: 1 }} value={value} onChange={(e) => setValue(e.target.value)} placeholder="e.g. NCT01234567" />
      <button className="btn sm primary" disabled={!value.trim()} onClick={() => void send({ type: "set_field", path: "protocol.study_identifiers", value: [{ system, value: value.trim() }] })}>
        Add
      </button>
    </>
  );
}

// ----------------------------------------------------------------------------- history / versions

function History({ session, canEdit }: { session: DraftSession; canEdit: boolean }) {
  const workId = session.work?.id ?? "";
  const [log, setLog] = useState<RevisionEntry[]>([]);
  const [versions, setVersions] = useState<Version[]>([]);
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const rev = session.state?.revision ?? 0;

  useEffect(() => {
    if (!workId) return;
    works.history(workId).then(setLog, () => setLog([]));
    works.versions(workId).then(setVersions, () => setVersions([]));
  }, [workId, rev]);

  async function freeze() {
    setBusy(true);
    setErr(null);
    try {
      await works.freeze(workId, { label: label.trim(), render_pdf: true });
      setLabel("");
      setVersions(await works.versions(workId));
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="card">
        <h2 className="caps">Export current draft (rev {rev})</h2>
        <div className="row">
          {(["pdf", "docx", "tex"] as const).map((k) => (
            <a key={k} className="btn sm" href={works.exportUrl(workId, k)} target="_blank" rel="noreferrer">
              {k.toUpperCase()}
            </a>
          ))}
        </div>
        <div className="tiny muted" style={{ marginTop: 6 }}>
          Draft exports are watermark-free but not frozen; freeze a version for anything you circulate.
        </div>
      </div>
      <div className="card">
        <h2 className="caps">Frozen versions</h2>
        {canEdit && (
          <div className="row" style={{ marginBottom: 8 }}>
            <input className="text" style={{ height: 28, flex: 1 }} placeholder="label, e.g. v0.3-internal" value={label} onChange={(e) => setLabel(e.target.value)} />
            <button className="btn sm primary" disabled={busy || !label.trim()} onClick={freeze}>
              {busy ? "Rendering…" : "Freeze"}
            </button>
          </div>
        )}
        {err && <div className="err tiny">{err}</div>}
        {versions.length === 0 && <div className="muted tiny">None yet.</div>}
        {versions.map((v) => (
          <div key={v.label} className="finding">
            <div className="row">
              <b>{v.label}</b>
              <span className="mono muted">rev {v.revision}</span>
              <span className="grow" />
              {v.readiness && <Chip kind={v.readiness.ready ? "ok" : "warning"}>{v.readiness.ready ? "review-ready" : "internal"}</Chip>}
            </div>
            <div className="tiny muted">
              {fmtDate(v.created_at)} · {v.frozen_by} · {v.completion?.pct ?? "—"}% complete
            </div>
            <div className="row" style={{ marginTop: 4 }}>
              {Object.entries(v.artifacts).map(([k, a]) =>
                a.available ? (
                  <a key={k} className="btn sm" href={works.versionFileUrl(workId, v.label, k as "tex" | "docx" | "pdf")} target="_blank" rel="noreferrer" title={a.sha256 ?? ""}>
                    {k.toUpperCase()}
                  </a>
                ) : (
                  <span key={k} className="chip" title="not produced (e.g. Tectonic missing)">
                    {k} —
                  </span>
                ),
              )}
            </div>
          </div>
        ))}
      </div>
      <div className="card">
        <h2 className="caps">Revision log</h2>
        {log.length === 0 && <div className="muted tiny">No edits yet.</div>}
        {log.map((r) => (
          <div key={r.revision} className="tiny" style={{ padding: "4px 0", borderBottom: "1px solid var(--slate-100)" }}>
            <div className="row">
              <span className="mono" style={{ width: 34 }}>
                r{r.revision}
              </span>
              <span className="grow">{r.summary}</span>
            </div>
            <div className="muted" style={{ paddingLeft: 42 }}>
              {r.actor} · {fmtDate(r.at)}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
