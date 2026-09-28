// The wire contract, typed straight off api/app/schemas.py's serialisers and the route answers.
// Nothing here is invented: every field exists on a response the API actually sends.

export type Source = "calendar" | "manual";
export type Step = "meeting" | "notes" | "points" | "done";
export type Kind = "action" | "decision" | "risk" | "question";
export type Status = "open" | "in_progress" | "blocked" | "done" | "dropped" | "decided";
export type Lifecycle = "active" | "deferred";
export type NoteSource = "gemini_doc" | "transcript" | "recap_email" | "paste" | "upload";
export type Mode = "append" | "fill";
export type Conflict = "skip" | "overwrite" | "insert";

export interface Me {
  id: string;
  email: string;
  name: string;
  role: "admin" | "member";
  is_admin: boolean;
}

export interface Attendee {
  email: string;
  name: string;
  response: string;
}

export interface AttachmentRef {
  title: string;
  kind: string;
  file_id: string;
  url: string;
}

/** A row of /meetings/list: a saved meeting (`id` set) or a calendar card not captured yet. */
export interface MeetingItem {
  id: string | null;
  key: string | null;
  source: Source;
  title: string;
  description: string;
  location: string;
  date: string | null;
  start: string | null;
  end: string | null;
  start_at: string | null;
  end_at: string | null;
  timezone: string;
  organizer_email: string;
  organizer_name: string;
  attendees: Attendee[];
  conference: { meet_link?: string };
  attachments: AttachmentRef[];
  calendar_event_id: string | null;
  ical_uid: string | null;
  recurring_event_id: string | null;
  html_link: string | null;
  workstream: string;
  step: Step;
  in_progress_by: string | null;
  last_synced_at?: string | null;
  updated_at?: string | null;
  editable: boolean;
  saved: boolean;
  notes_count: number;
  points_count: number;
}

export interface MeetingList {
  items: MeetingItem[];
  fetched_at: string;
  age_minutes: number;
  connections: string[];
  empty_hint: string;
}

export interface Note {
  id: string;
  meeting_id: string;
  source: NoteSource;
  origin_ref: string | null;
  title: string;
  text: string;
  word_count: number;
  text_hash: string;
  include: boolean;
  created_by: string;
  created_at: string | null;
}

export interface SourceOption {
  key: string;
  source: NoteSource | "paste";
  title: string;
  origin_ref: string;
  available: boolean;
  connection: string | null;
  tabs: string[];
  message: string;
}

export interface Sources {
  meeting_id: string;
  sources: SourceOption[];
  read_at: string;
}

export interface Point {
  id: string;
  meeting_id: string;
  extraction_id: string | null;
  kind: Kind;
  text: string;
  text_norm: string;
  evidence: string;
  owner_text: string;
  owner_email: string | null;
  owner_ambiguous: boolean;
  due_text: string;
  due_date: string | null;
  status: Status;
  workstream: string;
  lifecycle: Lifecycle;
  selected: boolean;
  updated_by: string | null;
  updated_at: string | null;
  deleted_at: string | null;
}

export interface TabMeta {
  sheet_id: string;
  title: string;
  index: number;
}

export interface Workbook {
  id: string;
  spreadsheet_id: string;
  name: string;
  url: string;
  connection_id: string | null;
  connected_by: string;
  connected_at: string | null;
  last_read_at: string | null;
  can_edit: boolean;
  last_error: string | null;
  tabs: TabMeta[];
}

export interface ConnectedWorkbook extends Workbook {
  read_through?: string;
  share_request?: string;
  needs_edit_access_from?: string[];
}

export interface LayoutOut {
  header_row: number;
  first_col: number;
  last_col: number;
  columns: Record<string, number>;
  key_col: number;
  key_prefix: string;
  last_table_row: number;
  header_score: number;
  formula_cols: number[];
  date_cols: number[];
}

export interface TabState {
  workbook_id: string;
  sheet_id: string;
  title: string;
  values: string[][];
  dropdowns: Record<string, string[]>;
  formula_cols: number[];
  date_cols: number[];
  layout: LayoutOut;
  region_hash: string;
  read_at: string;
  can_edit: boolean;
  workbook?: Workbook;
}

export interface PlanWrite {
  ref: string;
  r: number;
  c: number;
  value: string;
  kind: "new" | "key" | "conflict";
  existing: string | null;
  date: boolean;
}

export interface PlanOut {
  mode: "append" | "fill" | "add_row";
  insert_at: number | null;
  anchor: { r: number; c: number } | null;
  count: number;
  keys: string[];
  cells: string[];
  writes: PlanWrite[];
  moved: string[];
  conflicts: string[];
  field_order: { c: number; field: string }[];
  formula_fill: { col: number; source_row: number; target_rows: number[] }[];
  unmapped: string[];
  layout: LayoutOut | null;
}

export interface TransferPreview {
  plan: PlanOut;
  per_point: { point_id: string; row: number; cells: string[] }[];
  region_hash: string;
  read_at: string;
  tab: { workbook_id: string; sheet_id: string; title: string; values: string[][] };
  warnings: string[];
}

export interface Transfer {
  id: string;
  batch_id: string;
  at: string | null;
  actor: string;
  meeting_id: string | null;
  meeting_title: string;
  point_text: string;
  workbook_id: string;
  sheet_id: string;
  mode: string;
  cells: string[];
  snapshot: Record<string, unknown>;
  previous: Record<string, string>;
  undone_at: string | null;
  /** From `GET /transfers`: the ten-minute undo window is still open, by the server's clock. */
  can_undo?: boolean;
}

export interface TransferResult {
  batch_id: string;
  mode: string;
  cells: string[];
  transfers: Transfer[];
  undo_until: string;
  tab: TabState;
}

export interface SheetEdit {
  id: string;
  at: string | null;
  actor: string;
  workbook_id: string;
  sheet_id: string;
  cell: string;
  before: string;
  after: string;
  batch_id: string;
}

export interface SaveResult {
  ok: boolean;
  batch_id: string;
  edits: SheetEdit[];
  tab: TabState;
}

export interface SaveClash {
  cell: string;
  yours: string;
  theirs: string;
  was: string;
}

export interface AddRowResult {
  ok: boolean;
  batch_id: string;
  insert_at: number;
  keys: string[];
  cells: string[];
  transfer: Transfer | null;
  tab: TabState;
}

export interface Connection {
  id: string;
  email: string;
  name: string;
  scopes: string[];
  status: "ok" | "expired";
  connected_at: string | null;
  last_ok_at: string | null;
  last_error: string | null;
}

export interface Connections {
  connections: Connection[];
  warning: string;
  banner: string;
  /** Nothing connected at all: the app shows the notice with a Connect button. */
  first_run?: boolean;
  first_run_notice?: string;
}

/** `GET /admin/connections/status`: what the banner says, readable by everyone signed in. */
export interface ConnectionStatus {
  banner: string;
  first_run: boolean;
  first_run_notice: string;
  /** An admin: the first-run notice carries the Connect link. */
  can_connect: boolean;
}

export interface AllowEntry {
  email: string;
  role: "admin" | "member";
  added_by: string;
  added_at: string | null;
  signed_in: boolean;
}

export interface ActivityEntry {
  id: string;
  at: string | null;
  actor: string;
  text: string;
}

export type ExtractionJobStatus = "queued" | "running" | "done" | "error";

export interface ExtractionResult {
  extraction: Record<string, unknown> & { id: string; created_points?: number; status?: string };
  points: Point[];
  queued: boolean;
  /** With JOBS_ENABLED=1 the API answers `queued` and this is the path to poll. */
  poll?: string;
  job_id?: number | null;
}

/** One row of `GET /meetings/{id}/extractions`: who answered, newest first. */
export interface ExtractionRecord {
  id: string;
  meeting_id: string;
  provider: string;
  model: string;
  region: string | null;
  status: ExtractionJobStatus;
  fallback_from: string | null;
  /** A failed run is kept on record with the provider's message; newest first puts it on top. */
  error: string | null;
  /** Kept on the run: a transferred point is deleted, so a count taken later would shrink. */
  created_points?: number;
  /** When it ran (ISO). */
  at?: string | null;
}

/** `GET /extractions/{id}` - what the polling loop reads. */
export interface ExtractionStatus {
  id: string;
  meeting_id: string;
  status: ExtractionJobStatus;
  error?: string | null;
  created_points?: number;
  points: Point[];
}

export interface QuickPasteResult {
  meeting: MeetingItem;
  note: Note;
  created: boolean;
  created_meeting: boolean;
}

export interface UndoResult {
  ok: boolean;
  batch_id: string;
  restored_points: Point[];
  tab: TabState;
}
