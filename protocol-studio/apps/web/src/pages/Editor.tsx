/**
 * Editor: outline rail (15 entries with completion) · Docs-like sheet · analysis pane.
 *
 * Route: /editor/:workId/:sectionId?  (sectionId defaults to section.0).
 * The sheet shows one section at a time; each subsection lists its narrative
 * blocks (BlockEditor) plus an "add paragraph" affordance. Section 1 is a
 * generated view of the trial model and has no authored blocks.
 */
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AnalysisPane } from "../components/AnalysisPane";
import { BlockEditor } from "../components/BlockEditor";
import { Chip, Frame, Progress } from "../components/Frame";
import type { OutlineSection } from "../lib/api";
import { useDraft, type DraftSession } from "../lib/useDraft";

export function Editor() {
  const { workId = "", sectionId = "section.0" } = useParams();
  const session = useDraft(workId);
  const nav = useNavigate();
  const canEdit = session.work?.my_level === "edit" || session.work?.my_level === "admin";
  const section = session.outline.find((s) => s.id === sectionId) ?? null;

  const rail = (
    <>
      <Link to="/library" className="item">
        <span className="t muted">← Library</span>
      </Link>
      <div className="head caps">Outline</div>
      {session.outline.map((s) => (
        <button key={s.id} className={`item ${s.id === sectionId ? "active" : ""}`} onClick={() => nav(`/editor/${workId}/${s.id}`)}>
          <span className="n">{s.number}</span>
          <span className="t">{s.title}</span>
          {s.completion && !s.generated && <span className={`pct ${s.completion.pct === 100 ? "done" : ""}`}>{s.completion.pct}%</span>}
          {s.generated && <span className="pct">gen</span>}
        </button>
      ))}
    </>
  );

  return (
    <Frame rail={rail}>
      <div className="editwrap">
        <div className="edtop">
          <span className="title">{session.work?.title ?? "…"}</span>
          <span className="mono muted">{workId}</span>
          {session.work && <Chip>{session.work.kind}</Chip>}
          {session.evaluation && <Progress pct={session.evaluation.completion.overall.pct} drafted={session.evaluation.completion.overall.drafted_pct} />}
          <span className="grow" />
          <SaveIndicator session={session} />
          {!canEdit && session.work && <Chip>view only</Chip>}
        </div>
        <div className="editor">
          <div className="doc">
            <div className="sheet">
              {section ? <Sheet section={section} session={session} canEdit={canEdit} /> : <div className="muted">Loading…</div>}
            </div>
          </div>
          <AnalysisPane session={session} sectionId={sectionId} canEdit={canEdit} />
        </div>
      </div>
    </Frame>
  );
}

function SaveIndicator({ session }: { session: DraftSession }) {
  const { status, error, state } = session;
  const cls = status === "stale" || status === "error" ? "err" : status === "saving" ? "dirty" : "";
  const text =
    status === "saving" ? "Saving…" : status === "stale" ? "Stale — reloaded" : status === "error" ? "Save failed" : `Saved · rev ${state?.revision ?? 0}`;
  return (
    <span className={`save ${cls}`} title={error ?? ""}>
      <i />
      {text}
      {error && <span className="err tiny"> {error.slice(0, 120)}</span>}
    </span>
  );
}

function Sheet({ section, session, canEdit }: { section: OutlineSection; session: DraftSession; canEdit: boolean }) {
  const blocks = session.state?.blocks ?? [];
  const bySub = useMemo(() => {
    const m = new Map<string, typeof blocks>();
    for (const b of blocks.filter((x) => x.section_id === section.id).sort((a, b) => a.order - b.order)) {
      const arr = m.get(b.subsection_id) ?? [];
      arr.push(b);
      m.set(b.subsection_id, arr);
    }
    return m;
  }, [blocks, section.id]);

  return (
    <>
      <div className="row" style={{ fontFamily: "var(--ui)" }}>
        <span className="caps muted">Section {section.number}</span>
        <span className="grow" />
        {section.completion && !section.generated && (
          <span className="tiny muted">
            {section.completion.filled}/{section.completion.applicable} required slots · {section.completion.remaining.length} remaining
          </span>
        )}
      </div>
      <h2 className="sec">{section.title}</h2>
      {section.generated && <div className="gen">Generated from the trial model (Sections 3, 4 and 8). Edit the model, not this text.</div>}
      {section.generated && <Summary model={session.state?.model ?? {}} />}
      {section.subsections.map((sub) => (
        <div key={sub.id}>
          <h3 className="sub">
            {sub.title}
            <span className="mono" style={{ textTransform: "none", letterSpacing: 0 }}>
              {sub.id.replace("section.", "")}
            </span>
          </h3>
          {(bySub.get(sub.id) ?? []).map((b) => (
            <BlockEditor key={b.id} block={b} canEdit={canEdit} send={session.send} />
          ))}
          {canEdit && !section.generated && <AddBlock sectionId={section.id} subsectionId={sub.id} nextOrder={(bySub.get(sub.id) ?? []).length} session={session} />}
        </div>
      ))}
    </>
  );
}

function AddBlock({ sectionId, subsectionId, nextOrder, session }: { sectionId: string; subsectionId: string; nextOrder: number; session: DraftSession }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  if (!open)
    return (
      <div className="addblock" onClick={() => setOpen(true)}>
        + Add paragraph
      </div>
    );
  return (
    <div className="block">
      <textarea autoFocus rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="Write, or paste from a source (mark provenance afterwards)…" style={{ overflow: "auto" }} />
      <div className="tools">
        <button
          className="btn sm primary"
          disabled={!text.trim()}
          onClick={async () => {
            const ok = await session.send({ type: "upsert_block", section_id: sectionId, subsection_id: subsectionId, text: text.trim(), order: nextOrder, provenance: "author" });
            if (ok) {
              setText("");
              setOpen(false);
            }
          }}
        >
          Add
        </button>
        <button className="btn sm ghost" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </div>
  );
}

/** Section 1: a compact read-only rendering of key model entities. */
function Summary({ model }: { model: Record<string, unknown> }) {
  const named = (coll: string): { id: string; name: string; role?: string }[] => {
    const v = model[coll];
    return Array.isArray(v) ? (v as { id: string; name: string; role?: string }[]) : [];
  };
  const protocol = (model["protocol"] ?? {}) as Record<string, unknown>;
  const rows: [string, string][] = [
    ["Title", String(protocol["name"] ?? "—")],
    ["Phase", String(protocol["phase"] ?? "—")],
    ["Indication", String(protocol["indication"] ?? "—")],
    ["Sponsor", String(protocol["sponsor"] ?? "—")],
    ["Intent", String(protocol["intent"] ?? "—")],
    ["Objectives", named("objectives").map((o) => `${o.name}${o.role ? ` (${o.role})` : ""}`).join("; ") || "—"],
    ["Endpoints", named("endpoints").map((e) => `${e.name}${e.role ? ` (${e.role})` : ""}`).join("; ") || "—"],
    ["Participant paths", named("paths").map((p) => p.name).join("; ") || "—"],
    ["Populations", named("populations").map((p) => p.name).join("; ") || "—"],
    ["Assessments", named("assessments").map((a) => a.name).join("; ") || "—"],
  ];
  return (
    <table className="grid" style={{ fontFamily: "var(--ui)", fontSize: 13, marginTop: 12 }}>
      <tbody>
        {rows.map(([k, v]) => (
          <tr key={k}>
            <td className="muted" style={{ width: 160 }}>
              {k}
            </td>
            <td>{v}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
