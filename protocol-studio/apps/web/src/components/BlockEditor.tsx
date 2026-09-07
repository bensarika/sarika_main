/**
 * One narrative block on the document sheet.
 *
 * Text saves on blur (only if changed) as an `upsert_block` command; approval
 * and claims are explicit actions. A mismatch claim shows the two resolution
 * buttons the rules catalogue names: "Update model" / "Revert text".
 */
import { useEffect, useRef, useState } from "react";
import type { Block } from "../lib/api";
import type { Cmd } from "../lib/useDraft";
import { Chip } from "./Frame";

export function BlockEditor({ block, canEdit, send }: { block: Block; canEdit: boolean; send: (c: Cmd) => Promise<boolean> }) {
  const [text, setText] = useState(block.text);
  const [claimForm, setClaimForm] = useState(false);
  const ta = useRef<HTMLTextAreaElement>(null);

  useEffect(() => setText(block.text), [block.text]);
  useEffect(() => {
    const el = ta.current;
    if (el) {
      el.style.height = "0px";
      el.style.height = `${el.scrollHeight}px`;
    }
  }, [text]);

  const dirty = text !== block.text;
  const save = () => {
    if (!dirty) return;
    void send({
      type: "upsert_block",
      block_id: block.id,
      section_id: block.section_id,
      subsection_id: block.subsection_id,
      text,
      kind: block.kind,
      order: block.order,
      provenance: block.provenance === "imported" || block.provenance === "proposed" ? "author" : block.provenance,
    });
  };

  return (
    <div className={`block ${block.approval} ${block.provenance}`}>
      <textarea ref={ta} value={text} readOnly={!canEdit} onChange={(e) => setText(e.target.value)} onBlur={save} rows={1} spellCheck />
      <div className="tools">
        <Chip kind={block.provenance}>{block.provenance}</Chip>
        <Chip kind={block.approval === "approved" ? "approved" : undefined}>{block.approval}</Chip>
        {dirty && <span className="muted">unsaved — click away to save</span>}
        <span className="grow" />
        {canEdit && (
          <>
            {block.approval !== "approved" ? (
              <button className="btn sm ghost" onClick={() => void send({ type: "set_block_approval", block_id: block.id, approval: "approved" })}>
                Approve
              </button>
            ) : (
              <button className="btn sm ghost" onClick={() => void send({ type: "set_block_approval", block_id: block.id, approval: "unreviewed" })}>
                Unapprove
              </button>
            )}
            <button className="btn sm ghost" onClick={() => setClaimForm((v) => !v)}>
              + claim
            </button>
            <button className="btn sm ghost danger" onClick={() => void send({ type: "delete_block", block_id: block.id })}>
              Delete
            </button>
          </>
        )}
      </div>
      {block.claims.map((c) => (
        <div key={c.id} className={`claim ${c.state}`}>
          <Chip kind={c.state}>{c.state}</Chip>
          <span className="mono">{c.path}</span>
          <span>
            text says <b>{String(c.value)}</b>
            {c.state === "mismatch" && (
              <>
                {" "}
                · model says <b>{String(c.model_value)}</b>
              </>
            )}
          </span>
          <span className="grow" />
          {canEdit && c.state === "mismatch" && (
            <>
              <button className="btn sm" onClick={() => void send({ type: "resolve_claim", block_id: block.id, claim_id: c.id, resolution: "update_model" })}>
                Update model
              </button>
              <button className="btn sm" onClick={() => void send({ type: "resolve_claim", block_id: block.id, claim_id: c.id, resolution: "revert_text" })}>
                Revert text
              </button>
            </>
          )}
          {canEdit && (
            <button className="btn sm ghost" title="Remove claim" onClick={() => void send({ type: "set_claim", block_id: block.id, claim_id: c.id, path: c.path, remove: true })}>
              ×
            </button>
          )}
        </div>
      ))}
      {claimForm && <ClaimForm blockId={block.id} onDone={() => setClaimForm(false)} send={send} />}
    </div>
  );
}

/** Bind a phrase in this block to a model path + value, e.g. "Week 16" → endpoints[easi75].time.offset.value = 16. */
function ClaimForm({ blockId, onDone, send }: { blockId: string; onDone: () => void; send: (c: Cmd) => Promise<boolean> }) {
  const [path, setPath] = useState("");
  const [value, setValue] = useState("");
  const [text, setText] = useState("");
  return (
    <div className="claim" style={{ gap: 6 }}>
      <input className="text mono" placeholder="model path, e.g. endpoints[easi75].time.offset.value" value={path} onChange={(e) => setPath(e.target.value)} style={{ flex: 2, height: 26 }} />
      <input className="text" placeholder="value (16, true, “text”)" value={value} onChange={(e) => setValue(e.target.value)} style={{ flex: 1, height: 26 }} />
      <input className="text" placeholder="phrase in text (optional)" value={text} onChange={(e) => setText(e.target.value)} style={{ flex: 1, height: 26 }} />
      <button
        className="btn sm primary"
        disabled={!path}
        onClick={async () => {
          const ok = await send({ type: "set_claim", block_id: blockId, path, value: parseLoose(value), text });
          if (ok) onDone();
        }}
      >
        Bind
      </button>
      <button className="btn sm ghost" onClick={onDone}>
        Cancel
      </button>
    </div>
  );
}

/** Accept numbers, booleans and JSON literals typed as text; otherwise keep the string. */
export function parseLoose(s: string): unknown {
  const t = s.trim();
  if (t === "") return "";
  if (/^-?\d+(\.\d+)?$/.test(t)) return Number(t);
  if (t === "true" || t === "false") return t === "true";
  if (t === "null") return null;
  if (/^[[{"]/.test(t)) {
    try {
      return JSON.parse(t);
    } catch {
      return s;
    }
  }
  return s;
}
