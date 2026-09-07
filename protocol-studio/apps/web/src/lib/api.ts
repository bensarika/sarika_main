/**
 * Typed client for apps/api. One function per endpoint; no state.
 *
 * Conventions
 * - All requests are same-origin (Vite proxy in dev, API-served SPA in prod) so
 *   the signed session cookie rides along automatically.
 * - Non-2xx responses throw `ApiError` carrying the status and the JSON body,
 *   so callers can branch on `409` (stale revision) without string matching.
 * - Shapes below mirror the API's JSON exactly; if the API changes, change the
 *   type here first and let `tsc` find the call sites.
 */

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
  ) {
    super(`API ${status}`);
  }
}

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method,
    headers: body === undefined ? {} : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
  });
  const text = await r.text();
  const data: unknown = text ? JSON.parse(text) : null;
  if (!r.ok) throw new ApiError(r.status, data);
  return data as T;
}

// ----------------------------------------------------------------------------- auth

export interface User {
  id: number;
  email: string;
  name: string;
  role: "admin" | "author" | "reviewer" | string;
  active: boolean;
}
export interface AuthConfig {
  auth_mode: "dev" | "google";
  allowed_domain: string;
}

export const auth = {
  me: () => req<{ user: User }>("GET", "/auth/me"),
  config: () => req<AuthConfig>("GET", "/auth/config"),
  devLogin: () => req<{ user: User }>("POST", "/auth/dev-login"),
  logout: () => req<unknown>("POST", "/auth/logout"),
};

// ----------------------------------------------------------------------------- works

export interface Work {
  id: string;
  title: string;
  kind: string;
  indication: string;
  owner_id: number;
  starter: string;
  revision: number;
  created_at: string;
  updated_at: string;
  my_level: "view" | "edit" | "admin";
}

export interface Starter {
  id: string;
  title: string;
  kind: string;
  indication: string;
  description: string;
  protocol_id?: string;
}

export interface Claim {
  id: string;
  path: string;
  value: unknown;
  text: string;
  state: "checked" | "mismatch" | "unbound" | "unsupported" | "stale" | string;
  model_value: unknown;
}

export interface Block {
  id: string;
  section_id: string;
  subsection_id: string;
  order: number;
  kind: string;
  text: string;
  provenance: "author" | "imported" | "derived" | "proposed" | string;
  approval: "unreviewed" | "approved" | "rejected";
  claims: Claim[];
  updated_by: string;
  updated_at: string;
}

/** The mutable head of a work. `model` is the schema-governed trial model (opaque here). */
export interface DraftState {
  model: Record<string, unknown>;
  blocks: Block[];
  not_applicable: Record<string, string>;
  revision: number;
}

export interface Slot {
  id: string;
  label: string;
  kind: string;
  target_path: string | null;
  rule_id: string | null;
}
export interface SectionCompletion {
  section_id: string;
  number: number;
  title: string;
  pct: number;
  drafted_pct: number;
  filled: number;
  applicable: number;
  not_applicable: number;
  remaining: Slot[];
}
export interface Finding {
  rule_id: string;
  severity: "error" | "warning" | "incomplete" | "info" | "candidate";
  message: string;
  targets: string[];
  section_id: string | null;
  explanation: string;
  suggested_fix: string | null;
  needs_adjudication: boolean;
  revision: number;
  data: Record<string, unknown>;
  key: string;
  adjudication: "accepted" | "dismissed" | null;
}
export interface Evaluation {
  revision: number;
  findings: Finding[];
  counts: Record<string, number>;
  completion: {
    overall: { pct: number; drafted_pct: number; filled: number; applicable: number };
    sections: SectionCompletion[];
  };
  readiness: { ready: boolean; blockers: string[] };
}

export interface OutlineSection {
  id: string;
  number: number;
  title: string;
  generated: boolean;
  subsections: { id: string; title: string }[];
  completion: SectionCompletion | null;
}

/** Commands accepted by POST /commands. Discriminated on `type`; `base_revision` is mandatory. */
export type Command =
  | { type: "set_field"; base_revision: number; path: string; value: unknown }
  | { type: "add_entity"; base_revision: number; collection: string; entity: Record<string, unknown> }
  | { type: "remove_entity"; base_revision: number; collection: string; entity_id: string }
  | {
      type: "upsert_block";
      base_revision: number;
      block_id?: string | null;
      section_id: string;
      subsection_id: string;
      text: string;
      kind?: string;
      order?: number | null;
      provenance?: string;
    }
  | { type: "delete_block"; base_revision: number; block_id: string }
  | { type: "set_block_approval"; base_revision: number; block_id: string; approval: Block["approval"] }
  | {
      type: "set_claim";
      base_revision: number;
      block_id: string;
      claim_id?: string | null;
      path: string;
      value?: unknown;
      text?: string;
      remove?: boolean;
    }
  | {
      type: "resolve_claim";
      base_revision: number;
      block_id: string;
      claim_id: string;
      resolution: "update_model" | "revert_text";
    }
  | { type: "set_not_applicable"; base_revision: number; slot_id: string; reason: string | null };

export interface CommandResult {
  revision: number;
  summary: string;
  state: DraftState;
  evaluation: Evaluation;
}

export interface RevisionEntry {
  revision: number;
  actor: string;
  at: string;
  type: string;
  summary: string;
}

export interface Version {
  label: string;
  revision: number;
  note: string;
  frozen_by: string | null;
  created_at: string;
  readiness: Evaluation["readiness"] | null;
  completion: Evaluation["completion"]["overall"] | null;
  counts: Record<string, number> | null;
  artifacts: Record<string, { sha256: string | null; available: boolean }>;
}

export const works = {
  list: () => req<Work[]>("GET", "/api/works"),
  create: (body: { title: string; indication: string; kind: string; starter: string }) =>
    req<Work>("POST", "/api/works", body),
  get: (id: string) => req<Work>("GET", `/api/works/${id}`),
  draft: (id: string) => req<DraftState>("GET", `/api/works/${id}/draft`),
  evaluation: (id: string) => req<Evaluation>("GET", `/api/works/${id}/evaluation`),
  outline: (id: string) => req<OutlineSection[]>("GET", `/api/works/${id}/outline`),
  command: (id: string, cmd: Command) => req<CommandResult>("POST", `/api/works/${id}/commands`, cmd),
  adjudicate: (id: string, body: { finding_key: string; decision: "accepted" | "dismissed"; note?: string; revision: number }) =>
    req<unknown>("POST", `/api/works/${id}/adjudications`, body),
  history: (id: string) => req<RevisionEntry[]>("GET", `/api/works/${id}/history`),
  setPermission: (id: string, body: { email: string; level: "view" | "edit" | "admin" | null }) =>
    req<unknown>("PUT", `/api/works/${id}/permissions`, body),
  versions: (id: string) => req<Version[]>("GET", `/api/works/${id}/versions`),
  freeze: (id: string, body: { label: string; note?: string; render_pdf?: boolean }) =>
    req<Version>("POST", `/api/works/${id}/versions`, body),
  versionFileUrl: (id: string, label: string, kind: "tex" | "docx" | "pdf") =>
    `/api/works/${id}/versions/${encodeURIComponent(label)}/file/${kind}`,
  exportUrl: (id: string, kind: "tex" | "docx" | "pdf") => `/api/works/${id}/export/${kind}`,
};

export const library = {
  starters: () => req<Starter[]>("GET", "/api/library/starters"),
  rules: () =>
    req<{ id: string; status: "implemented" | "planned"; name: string; check_type: string; default_result: string; check: string }[]>(
      "GET",
      "/api/reference/rules",
    ),
};

// ----------------------------------------------------------------------------- admin

export interface AdminUser extends User {
  created_at: string;
  last_seen_at: string | null;
}
export interface UsageRow {
  email: string;
  commands: number;
  exports: number;
  logins: number;
  freezes: number;
  other: number;
}
export interface AuditRow {
  id: number;
  at: string;
  actor: string | null;
  work_id: string | null;
  action: string;
  detail: Record<string, unknown>;
}

export const admin = {
  users: () => req<AdminUser[]>("GET", "/api/admin/users"),
  addUser: (body: { email: string; name?: string; role?: string }) => req<AdminUser>("POST", "/api/admin/users", body),
  patchUser: (id: number, body: { role?: string; active?: boolean; name?: string }) =>
    req<AdminUser>("PATCH", `/api/admin/users/${id}`, body),
  usage: () => req<UsageRow[]>("GET", "/api/admin/usage"),
  audit: () => req<AuditRow[]>("GET", "/api/admin/audit"),
};
