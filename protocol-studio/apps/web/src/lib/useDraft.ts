/**
 * Draft session for one work: head state, evaluation, outline, and a `send`
 * that applies commands with optimistic concurrency.
 *
 * Every command is stamped with the current head revision. A 409 means someone
 * else (or another tab) committed first: we reload the head and surface a
 * "stale" notice instead of silently retrying, because a semantic edit made
 * against an old model may no longer make sense (docs/01_architecture.md §5).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, works, type Command, type DraftState, type Evaluation, type OutlineSection, type Work } from "./api";

export type SaveStatus = "idle" | "saving" | "saved" | "stale" | "error";

/** A command minus `base_revision`; the hook fills that in. */
export type Cmd = Command extends infer C ? (C extends { base_revision: number } ? Omit<C, "base_revision"> : never) : never;

export interface DraftSession {
  work: Work | null;
  state: DraftState | null;
  evaluation: Evaluation | null;
  outline: OutlineSection[];
  status: SaveStatus;
  error: string | null;
  lastSummary: string;
  send: (cmd: Cmd) => Promise<boolean>;
  reload: () => Promise<void>;
  refreshOutline: () => Promise<void>;
}

export function useDraft(workId: string): DraftSession {
  const [work, setWork] = useState<Work | null>(null);
  const [state, setState] = useState<DraftState | null>(null);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [outline, setOutline] = useState<OutlineSection[]>([]);
  const [status, setStatus] = useState<SaveStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [lastSummary, setLastSummary] = useState("");
  // Serialise commands: the UI can fire blur + click in the same tick and each
  // must observe the revision produced by the previous one.
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const revision = useRef(0);

  const refreshOutline = useCallback(async () => setOutline(await works.outline(workId)), [workId]);

  const reload = useCallback(async () => {
    const [w, s, ev, o] = await Promise.all([works.get(workId), works.draft(workId), works.evaluation(workId), works.outline(workId)]);
    revision.current = s.revision;
    setWork(w);
    setState(s);
    setEvaluation(ev);
    setOutline(o);
  }, [workId]);

  useEffect(() => {
    setStatus("idle");
    setError(null);
    reload().catch((e: unknown) => {
      setStatus("error");
      setError(String(e));
    });
  }, [reload]);

  const send = useCallback(
    (cmd: Cmd): Promise<boolean> => {
      const run = async (): Promise<boolean> => {
        setStatus("saving");
        try {
          const full = { ...cmd, base_revision: revision.current } as Command;
          const res = await works.command(workId, full);
          revision.current = res.revision;
          setState(res.state);
          setEvaluation(res.evaluation);
          setLastSummary(res.summary);
          setStatus("saved");
          setError(null);
          void refreshOutline();
          return true;
        } catch (e) {
          if (e instanceof ApiError && e.status === 409) {
            setStatus("stale");
            setError("Someone else saved first — reloaded the latest revision. Re-apply your change.");
            await reload();
          } else {
            setStatus("error");
            const body = e instanceof ApiError ? (e.body as { detail?: unknown } | null) : null;
            setError(body?.detail ? JSON.stringify(body.detail) : String(e));
          }
          return false;
        }
      };
      const p = queue.current.then(run, run);
      queue.current = p;
      return p;
    },
    [workId, reload, refreshOutline],
  );

  return { work, state, evaluation, outline, status, error, lastSummary, send, reload, refreshOutline };
}
