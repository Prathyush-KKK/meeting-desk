// TanStack Query hooks, one group per route group. There is no client-side store: the server is the
// store, lists poll every 15 s, the live sheet tab every 60 s, and a
// point edit is applied optimistically and rolled back if the API refuses it.

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";
import { api, ApiError } from "@/api/client";
import type {
  ActivityEntry,
  AddRowResult,
  AllowEntry,
  Conflict,
  ConnectedWorkbook,
  ConnectionStatus,
  Connections,
  ExtractionRecord,
  ExtractionResult,
  ExtractionStatus,
  Lifecycle,
  Me,
  MeetingItem,
  MeetingList,
  Mode,
  Note,
  Point,
  QuickPasteResult,
  SaveResult,
  Sources,
  TabState,
  Transfer,
  TransferPreview,
  TransferResult,
  UndoResult,
  Workbook,
} from "@/api/types";

export const LIST_POLL_MS = 15_000;
export const TAB_POLL_MS = 60_000;

export const qk = {
  me: ["me"] as const,
  meetings: ["meetings"] as const,
  meeting: (id: string) => ["meeting", id] as const,
  notes: (meetingId: string) => ["notes", meetingId] as const,
  sources: (meetingId: string) => ["sources", meetingId] as const,
  points: (meetingId: string | null, lifecycle: Lifecycle) => ["points", meetingId ?? "all", lifecycle] as const,
  workbooks: ["workbooks"] as const,
  tab: (workbookId: string, sheetId: string) => ["tab", workbookId, sheetId] as const,
  transfers: (workbookId?: string) => ["transfers", workbookId ?? "all"] as const,
  // Under "transfers" so invalidateAfterWrite reaches it; "meeting" keeps it off any workbook's key.
  meetingTransfers: (meetingId: string) => ["transfers", "meeting", meetingId] as const,
  connections: ["connections"] as const,
  allowList: ["allow-list"] as const,
  activity: ["activity"] as const,
  extractions: (meetingId: string) => ["extractions", meetingId] as const,
  connectionStatus: ["connection-status"] as const,
};

type ListOptions<T> = Omit<UseQueryOptions<T, ApiError, T>, "queryKey" | "queryFn">;

function list<T>(key: readonly unknown[], fn: () => Promise<T>, options?: ListOptions<T>) {
  return { queryKey: key, queryFn: fn, refetchInterval: LIST_POLL_MS, ...options };
}

/** Everything a transfer, an add-row or a sheet save can have moved. */
export function invalidateAfterWrite(client: QueryClient, workbookId?: string, sheetId?: string): void {
  void client.invalidateQueries({ queryKey: ["points"] });
  void client.invalidateQueries({ queryKey: qk.meetings });
  void client.invalidateQueries({ queryKey: qk.workbooks });
  void client.invalidateQueries({ queryKey: ["transfers"] });
  void client.invalidateQueries({ queryKey: qk.activity });
  if (workbookId && sheetId) void client.invalidateQueries({ queryKey: qk.tab(workbookId, sheetId) });
  else void client.invalidateQueries({ queryKey: ["tab"] });
}

// --- who am I -------------------------------------------------------------------------------------

export function useMe() {
  return useQuery<Me, ApiError>({
    queryKey: qk.me,
    queryFn: () => api.get<Me>("/auth/me"),
    retry: (count, error) => !(error instanceof ApiError && (error.isAuth || error.isForbidden)) && count < 2,
    refetchOnWindowFocus: true,
    staleTime: 60_000,
  });
}

// --- step 1: meetings -----------------------------------------------------------------------------

export function useMeetings() {
  return useQuery<MeetingList, ApiError>(list(qk.meetings, () => api.get<MeetingList>("/meetings/list")));
}

export function useRefreshMeetings() {
  const client = useQueryClient();
  return useMutation<MeetingList, ApiError, void>({
    mutationFn: () => api.get<MeetingList>("/meetings/list", { refresh: true }),
    onSuccess: (data) => client.setQueryData(qk.meetings, data),
  });
}

/** Selecting a calendar card upserts the record on calendar_event_id. */
export function useCaptureCalendarEvent() {
  const client = useQueryClient();
  return useMutation<MeetingItem, ApiError, { calendar_event_id: string; workstream?: string }>({
    mutationFn: (body) => api.post<MeetingItem>("/meetings/from-calendar", body),
    onSuccess: () => void client.invalidateQueries({ queryKey: qk.meetings }),
  });
}

export interface ManualMeetingIn {
  title: string;
  date: string;
  start: string;
  end: string;
  description?: string;
  location?: string;
  workstream?: string;
  attendees?: { name: string; email: string; response: string }[];
}

export function useCreateManualMeeting() {
  const client = useQueryClient();
  return useMutation<MeetingItem, ApiError, ManualMeetingIn>({
    mutationFn: (body) => api.post<MeetingItem>("/meetings/manual", body),
    onSuccess: () => void client.invalidateQueries({ queryKey: qk.meetings }),
  });
}

export function usePatchMeeting() {
  const client = useQueryClient();
  return useMutation<MeetingItem, ApiError, { id: string; patch: Partial<ManualMeetingIn> & { step?: string } }>({
    mutationFn: ({ id, patch }) => api.patch<MeetingItem>(`/meetings/${id}`, patch),
    onSuccess: (data) => {
      client.setQueryData(qk.meeting(data.id ?? ""), data);
      void client.invalidateQueries({ queryKey: qk.meetings });
    },
  });
}

export function useDeleteMeeting() {
  const client = useQueryClient();
  return useMutation<{ ok: boolean; id: string }, ApiError, string>({
    mutationFn: (id) => api.del(`/meetings/${id}`),
    onSuccess: () => void client.invalidateQueries({ queryKey: qk.meetings }),
  });
}

/** The Undo on a deleted manual meeting's toast: the delete is soft, so this brings it back. */
export function useRestoreMeeting() {
  const client = useQueryClient();
  return useMutation<MeetingItem, ApiError, string>({
    mutationFn: (id) => api.post<MeetingItem>(`/meetings/${id}/restore`),
    onSuccess: () => void client.invalidateQueries({ queryKey: qk.meetings }),
  });
}

export function useResyncMeeting() {
  const client = useQueryClient();
  return useMutation<MeetingItem, ApiError, string>({
    mutationFn: (id) => api.post<MeetingItem>(`/meetings/${id}/resync`),
    onSuccess: () => void client.invalidateQueries({ queryKey: qk.meetings }),
  });
}

/** The paste field at the top of Capture. */
export function useQuickPaste() {
  const client = useQueryClient();
  return useMutation<QuickPasteResult, ApiError, { text: string; meeting_id?: string | null }>({
    mutationFn: (body) => api.post<QuickPasteResult>("/notes/quick", body),
    onSuccess: (data) => {
      void client.invalidateQueries({ queryKey: qk.meetings });
      void client.invalidateQueries({ queryKey: qk.notes(data.meeting.id ?? "") });
      void client.invalidateQueries({ queryKey: qk.activity });
    },
  });
}

// --- step 2: notes --------------------------------------------------------------------------------

export function useNotes(meetingId: string | null) {
  return useQuery<Note[], ApiError>({
    ...list(qk.notes(meetingId ?? ""), () => api.get<Note[]>("/notes", { meeting_id: meetingId ?? "" })),
    enabled: !!meetingId,
  });
}

export function useSources(meetingId: string | null) {
  return useQuery<Sources, ApiError>({
    queryKey: qk.sources(meetingId ?? ""),
    queryFn: () => api.get<Sources>("/notes/sources", { meeting_id: meetingId ?? "" }),
    enabled: !!meetingId,
    staleTime: 30_000,
  });
}

function notesInvalidation(client: QueryClient, meetingId: string) {
  void client.invalidateQueries({ queryKey: qk.notes(meetingId) });
  void client.invalidateQueries({ queryKey: qk.sources(meetingId) });
  void client.invalidateQueries({ queryKey: qk.meetings });
  void client.invalidateQueries({ queryKey: qk.activity });
}

export function useImportNote(meetingId: string) {
  const client = useQueryClient();
  return useMutation<
    { note: Note; created: boolean; connection?: string; tab?: string },
    ApiError,
    { source: "gemini_doc" | "transcript" | "recap_email"; origin_ref?: string; tab?: string }
  >({
    mutationFn: (body) => api.post("/notes/import", { meeting_id: meetingId, ...body }),
    onSuccess: () => notesInvalidation(client, meetingId),
  });
}

export function usePasteNote(meetingId: string) {
  const client = useQueryClient();
  return useMutation<
    { note: Note; created: boolean; truncated: boolean },
    ApiError,
    { text: string; title?: string; source?: "paste" | "upload" }
  >({
    mutationFn: (body) => api.post("/notes/paste", { meeting_id: meetingId, ...body }),
    onSuccess: () => notesInvalidation(client, meetingId),
  });
}

export function usePatchNote(meetingId: string) {
  const client = useQueryClient();
  return useMutation<Note, ApiError, { id: string; include?: boolean; title?: string }, { previous?: Note[] }>({
    mutationFn: ({ id, ...patch }) => api.patch<Note>(`/notes/${id}`, patch),
    onMutate: async ({ id, include }) => {
      if (include === undefined) return { previous: undefined };
      await client.cancelQueries({ queryKey: qk.notes(meetingId) });
      const previous = client.getQueryData<Note[]>(qk.notes(meetingId));
      if (previous) {
        client.setQueryData<Note[]>(
          qk.notes(meetingId),
          previous.map((n) => (n.id === id ? { ...n, include } : n)),
        );
      }
      return { previous };
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) client.setQueryData(qk.notes(meetingId), context.previous);
    },
    onSettled: () => void client.invalidateQueries({ queryKey: qk.notes(meetingId) }),
  });
}

/** Pasted onto the wrong meeting: move the note rather than retype it. */
export function useMoveNote(meetingId: string) {
  const client = useQueryClient();
  return useMutation<Note, ApiError, { id: string; meeting_id: string }>({
    mutationFn: ({ id, meeting_id }) => api.post<Note>(`/notes/${id}/move`, { meeting_id }),
    onSuccess: (_note, { meeting_id }) => {
      notesInvalidation(client, meetingId);
      notesInvalidation(client, meeting_id);
    },
  });
}

export function useDeleteNote(meetingId: string) {
  const client = useQueryClient();
  return useMutation<{ ok: boolean }, ApiError, string>({
    mutationFn: (id) => api.del(`/notes/${id}`),
    onSuccess: () => notesInvalidation(client, meetingId),
  });
}

// --- step 3: points -------------------------------------------------------------------------------

export function usePoints(meetingId: string | null, lifecycle: Lifecycle = "active", enabled = true) {
  return useQuery<Point[], ApiError>({
    ...list(qk.points(meetingId, lifecycle), () =>
      api.get<Point[]>("/points", { meeting_id: meetingId ?? undefined, lifecycle }),
    ),
    enabled,
  });
}

export interface PointPatch {
  kind?: string;
  text?: string;
  owner_text?: string;
  due_text?: string;
  status?: string;
  workstream?: string;
  selected?: boolean;
  lifecycle?: Lifecycle;
}

/**
 * Field edits autosave. The row moves the moment it is typed and goes back where it was if the API
 * refuses - nothing is silently discarded.
 */
export function usePatchPoint(meetingId: string | null, lifecycle: Lifecycle = "active") {
  const client = useQueryClient();
  const key = qk.points(meetingId, lifecycle);
  return useMutation<Point, ApiError, { id: string; patch: PointPatch }, { previous?: Point[] }>({
    mutationFn: ({ id, patch }) => api.patch<Point>(`/points/${id}`, patch),
    onMutate: async ({ id, patch }) => {
      await client.cancelQueries({ queryKey: key });
      const previous = client.getQueryData<Point[]>(key);
      if (previous) {
        client.setQueryData<Point[]>(
          key,
          previous.map((p) => (p.id === id ? ({ ...p, ...patch } as Point) : p)),
        );
      }
      return { previous };
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) client.setQueryData(key, context.previous);
    },
    onSuccess: (point) => {
      const current = client.getQueryData<Point[]>(key);
      if (current) client.setQueryData<Point[]>(key, current.map((p) => (p.id === point.id ? point : p)));
    },
  });
}

export const AUTOSAVE_MS = 500;

/** Selects and checkboxes are one decision, so they go straight out; typing waits 500 ms. */
const IMMEDIATE_FIELDS = new Set(["selected", "kind", "status", "owner_text", "workstream", "lifecycle"]);

/**
 * Autosave for the points grid.
 *
 * A keystroke lands in a local draft at once (so neither a slow request nor the 15 s poll can pull
 * the text out from under the person), the PATCH goes out 500 ms later, and the draft is dropped
 * only when the answer to *that* edit comes back. Leaving the step flushes what is still pending.
 */
export function usePointEditor(meetingId: string | null, lifecycle: Lifecycle = "active") {
  const patch = usePatchPoint(meetingId, lifecycle);
  const drafts = useRef<Record<string, PointPatch>>({});
  const versions = useRef<Record<string, number>>({});
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const [, bump] = useReducer((n: number) => n + 1, 0);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  const flush = useCallback(
    (id: string) => {
      const draft = drafts.current[id];
      if (!draft) return;
      const version = versions.current[id] ?? 0;
      patch.mutate(
        { id, patch: draft },
        {
          onSuccess: () => setSavedAt(new Date().toISOString()),
          onSettled: () => {
            if (versions.current[id] === version) {
              delete drafts.current[id];
              bump();
            }
          },
        },
      );
    },
    [patch],
  );

  const edit = useCallback(
    (id: string, body: PointPatch) => {
      drafts.current = { ...drafts.current, [id]: { ...drafts.current[id], ...body } };
      versions.current[id] = (versions.current[id] ?? 0) + 1;
      bump();
      clearTimeout(timers.current[id]);
      if (Object.keys(body).every((k) => IMMEDIATE_FIELDS.has(k))) flush(id);
      else timers.current[id] = setTimeout(() => flush(id), AUTOSAVE_MS);
    },
    [flush],
  );

  useEffect(() => {
    const pendingTimers = timers.current;
    const pendingDrafts = drafts.current;
    return () => {
      // Unmounting: the component's mutation observer is going away, so send what is left directly.
      for (const timer of Object.values(pendingTimers)) clearTimeout(timer);
      for (const [id, body] of Object.entries(pendingDrafts)) {
        void api.patch(`/points/${id}`, body).catch(() => undefined);
      }
    };
  }, []);

  /** The rows as the person sees them: the server's points with their unsaved edits on top. */
  const merge = useCallback(
    (points: Point[]) => points.map((p) => (drafts.current[p.id] ? ({ ...p, ...drafts.current[p.id] } as Point) : p)),
    [],
  );

  return { edit, merge, savedAt, pending: Object.keys(drafts.current).length };
}

export function useBulkPatchPoints(meetingId: string | null, lifecycle: Lifecycle = "active") {
  const client = useQueryClient();
  const key = qk.points(meetingId, lifecycle);
  return useMutation<Point[], ApiError, { ids: string[]; patch: PointPatch }, { previous?: Point[] }>({
    mutationFn: (body) => api.post<Point[]>("/points/bulk", body),
    onMutate: async ({ ids, patch }) => {
      await client.cancelQueries({ queryKey: key });
      const previous = client.getQueryData<Point[]>(key);
      if (previous) {
        const wanted = new Set(ids);
        client.setQueryData<Point[]>(
          key,
          previous.map((p) => (wanted.has(p.id) ? ({ ...p, ...patch } as Point) : p)),
        );
      }
      return { previous };
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) client.setQueryData(key, context.previous);
    },
    onSettled: () => void client.invalidateQueries({ queryKey: ["points"] }),
  });
}

export function useAddPoint(meetingId: string) {
  const client = useQueryClient();
  return useMutation<Point, ApiError, { kind?: string; text: string; workstream?: string }>({
    mutationFn: (body) => api.post<Point>("/points", { meeting_id: meetingId, ...body }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["points"] }),
  });
}

export function useDeferPoints() {
  const client = useQueryClient();
  return useMutation<Point[], ApiError, string[]>({
    mutationFn: (ids) =>
      ids.length === 1
        ? api.post<Point>(`/points/${ids[0]}/defer`).then((p) => [p])
        : api.post<Point[]>("/points/defer", { ids }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ["points"] });
      void client.invalidateQueries({ queryKey: qk.meetings });
    },
  });
}

export function useRestorePoint() {
  const client = useQueryClient();
  return useMutation<Point, ApiError, string>({
    mutationFn: (id) => api.post<Point>(`/points/${id}/restore`),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ["points"] });
      void client.invalidateQueries({ queryKey: qk.meetings });
    },
  });
}

export interface DeletedPoint {
  ok: boolean;
  id: string;
  undo_until: string;
  recoverable_until: string;
  undo_url: string;
}

export function useDeletePoint() {
  const client = useQueryClient();
  return useMutation<DeletedPoint, ApiError, string>({
    mutationFn: (id) => api.del<DeletedPoint>(`/points/${id}`),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ["points"] });
      void client.invalidateQueries({ queryKey: qk.meetings });
      void client.invalidateQueries({ queryKey: qk.activity });
    },
  });
}

export function useCopyPointsAsText() {
  return useMutation<{ text: string }, ApiError, string[]>({
    mutationFn: (ids) => api.post<{ text: string }>("/points/copy-text", { ids }),
  });
}

export const EXTRACTION_POLL_MS = 2_000;
/** A run that has not landed in ten minutes is not going to; the notes are untouched either way. */
export const EXTRACTION_POLL_TIMEOUT_MS = 10 * 60_000;

export type ExtractPhase = "idle" | "running" | "queued" | "done" | "error" | "cancelled";

export class ExtractionCancelled extends Error {
  constructor() {
    super("Extraction cancelled. It may still finish on the server; the points will appear.");
    this.name = "ExtractionCancelled";
  }
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export interface PollDeps {
  get: (path: string) => Promise<ExtractionStatus>;
  wait: (ms: number) => Promise<void>;
  now: () => number;
  cancelled: () => boolean;
  onPhase?: (phase: ExtractPhase) => void;
  intervalMs?: number;
  timeoutMs?: number;
}

/**
 * The queued path. With `JOBS_ENABLED=1` the API answers `{queued: true}` and the points arrive
 * later, so `GET /extractions/{id}` is read every 2 s until it says `done` or `error`.
 *
 * Kept out of the hook and given its dependencies so a test can drive it with no timers and no
 * network - which is the only way to assert "every 2 s until done, and Cancel stops it".
 */
export async function pollExtraction(extractionId: string, deps: PollDeps): Promise<ExtractionStatus> {
  const interval = deps.intervalMs ?? EXTRACTION_POLL_MS;
  const timeout = deps.timeoutMs ?? EXTRACTION_POLL_TIMEOUT_MS;
  const startedAt = deps.now();
  for (;;) {
    if (deps.cancelled()) throw new ExtractionCancelled();
    await deps.wait(interval);
    if (deps.cancelled()) throw new ExtractionCancelled();
    const state = await deps.get(`/extractions/${extractionId}`);
    if (state.status === "error") throw new Error(state.error || "Extraction failed.");
    if (state.status === "done") return state;
    deps.onPhase?.(state.status);
    if (deps.now() - startedAt > timeout) {
      throw new Error("Extraction is still running after 10 minutes. The notes are untouched; try again.");
    }
  }
}

/**
 * Extract, whichever way the API answers.
 *
 * `JOBS_ENABLED=0`: one POST comes back with the points. `JOBS_ENABLED=1`: the POST answers
 * `queued` and this polls until the job lands. Either way the promise resolves with the points, so
 * the Notes step does not care which deployment it is talking to. `cancel()` stops the polling -
 * the job itself keeps running on the worker, which the message says.
 */
export function useExtract(meetingId: string) {
  const client = useQueryClient();
  const [phase, setPhase] = useState<ExtractPhase>("idle");
  const cancelled = useRef(false);

  useEffect(() => () => { cancelled.current = true; }, []);

  const cancel = useCallback(() => {
    cancelled.current = true;
    setPhase("cancelled");
  }, []);

  const mutation = useMutation<ExtractionResult, Error, void>({
    mutationFn: async () => {
      cancelled.current = false;
      setPhase("running");
      let result = await api.post<ExtractionResult>(`/meetings/${meetingId}/extract`);
      if (result.queued) {
        setPhase("queued");
        const landed = await pollExtraction(String(result.extraction.id), {
          get: (path) => api.get<ExtractionStatus>(path),
          wait: sleep,
          now: () => Date.now(),
          cancelled: () => cancelled.current,
          onPhase: setPhase,
        });
        result = { ...result, points: landed.points, queued: false };
      }
      // Step 3 opens with the action items already ticked; the API stores `selected` per point, so
      // one bulk call sets it.
      const actions = result.points.filter((p) => p.kind === "action" && !p.selected).map((p) => p.id);
      if (actions.length) await api.post("/points/bulk", { ids: actions, patch: { selected: true } });
      setPhase("done");
      return result;
    },
    onError: () => setPhase((p) => (p === "cancelled" ? p : "error")),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ["points"] });
      void client.invalidateQueries({ queryKey: qk.meetings });
      void client.invalidateQueries({ queryKey: qk.activity });
      void client.invalidateQueries({ queryKey: qk.extractions(meetingId) });
    },
  });

  return {
    ...mutation,
    phase,
    cancel,
    /** True while the job is on the queue: that is when Cancel is worth offering. */
    isPolling: phase === "queued",
  };
}

/** Who extracted this meeting's points, newest first: the label on Step 3 reads it. */
export function useExtractions(meetingId: string | null) {
  return useQuery<ExtractionRecord[], ApiError>({
    queryKey: qk.extractions(meetingId ?? ""),
    queryFn: () => api.get<ExtractionRecord[]>(`/meetings/${meetingId}/extractions`),
    enabled: !!meetingId,
  });
}

// --- workbooks and the live tab -------------------------------------------------------------------

export function useWorkbooks() {
  return useQuery<Workbook[], ApiError>(list(qk.workbooks, () => api.get<Workbook[]>("/workbooks")));
}

export function useConnectWorkbook() {
  const client = useQueryClient();
  return useMutation<ConnectedWorkbook, ApiError, string>({
    mutationFn: (url) => api.post<ConnectedWorkbook>("/workbooks/connect", { url }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: qk.workbooks });
      void client.invalidateQueries({ queryKey: qk.activity });
    },
  });
}

export function useDisconnectWorkbook() {
  const client = useQueryClient();
  return useMutation<{ ok: boolean }, ApiError, string>({
    mutationFn: (id) => api.del(`/workbooks/${id}`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: qk.workbooks });
      void client.invalidateQueries({ queryKey: qk.activity });
    },
  });
}

/** The live tab. Auto-refresh every 60 s while the page is visible. */
export function useTab(workbookId: string | null, sheetId: string | null) {
  return useQuery<TabState, ApiError>({
    queryKey: qk.tab(workbookId ?? "", sheetId ?? ""),
    queryFn: () => api.get<TabState>(`/workbooks/${workbookId}/tabs/${sheetId}`),
    enabled: !!workbookId && !!sheetId,
    refetchInterval: TAB_POLL_MS,
    refetchIntervalInBackground: false,
  });
}

export function useTransfers(workbookId?: string) {
  return useQuery<Transfer[], ApiError>(
    list(qk.transfers(workbookId), () => api.get<Transfer[]>("/transfers", { workbook_id: workbookId })),
  );
}

/** What left one meeting, for which sheet and whether it came back: its history, newest first. */
export function useMeetingTransfers(meetingId: string | null) {
  return useQuery<Transfer[], ApiError>({
    ...list(qk.meetingTransfers(meetingId ?? ""), () => api.get<Transfer[]>("/transfers", { meeting_id: meetingId ?? "" })),
    enabled: !!meetingId,
  });
}

// --- step 4: transfer -----------------------------------------------------------------------------

export interface PreviewIn {
  workbook_id: string;
  sheet_id: string;
  mode: Mode;
  point_ids: string[];
  anchor?: { r: number; c: number } | null;
  conflict?: Conflict;
  write_keys?: boolean;
}

/**
 * The server's plan. Re-planned whenever the inputs change and after a 409, which is how the
 * "someone edited the tab between preview and write" case resolves itself.
 */
export function useTransferPreview(input: PreviewIn | null) {
  return useQuery<TransferPreview, ApiError>({
    queryKey: ["transfer-preview", input],
    queryFn: () => api.post<TransferPreview>("/transfers/preview", input as PreviewIn),
    enabled: !!input && input.point_ids.length > 0,
    retry: false,
    gcTime: 0,
    staleTime: 0,
  });
}

/**
 * `batch_id` is the client's idempotency key. It is minted per user intent in
 * the page - see `lib/batch.ts` - not here, because a key made per call would be a fresh one on
 * every retry and would not stop anything.
 */
export function useTransferExecute() {
  const client = useQueryClient();
  return useMutation<TransferResult, ApiError, PreviewIn & { region_hash: string; allow_repeat?: boolean; batch_id?: string }>({
    mutationFn: (body) => api.post<TransferResult>("/transfers/execute", body),
    onSuccess: (_result, variables) => invalidateAfterWrite(client, variables.workbook_id, variables.sheet_id),
  });
}

export function useUndoTransfer() {
  const client = useQueryClient();
  return useMutation<UndoResult, ApiError, string>({
    mutationFn: (batchId) => api.post<UndoResult>(`/transfers/${batchId}/undo`),
    onSuccess: (result) => invalidateAfterWrite(client, result.tab?.workbook_id, result.tab?.sheet_id),
  });
}

// --- the Sheets page ------------------------------------------------------------------------------

export interface SheetSaveIn {
  workbook_id: string;
  sheet_id: string;
  /** `before` is the value the cell held when the person changed it, not the latest poll's. */
  edits: { cell: string; before: string; after: string }[];
  batch_id?: string;
}

export function useSaveSheet() {
  const client = useQueryClient();
  return useMutation<SaveResult, ApiError, SheetSaveIn>({
    mutationFn: (body) => api.post<SaveResult>("/sheets/save", body),
    onSuccess: (result, variables) => {
      client.setQueryData(qk.tab(variables.workbook_id, variables.sheet_id), result.tab);
      invalidateAfterWrite(client, variables.workbook_id, variables.sheet_id);
    },
  });
}

export interface AddRowIn {
  workbook_id: string;
  sheet_id: string;
  /** Mandatory server-side: 64 hex characters, always compared. */
  region_hash: string;
  point_id?: string | null;
  values?: Record<string, string>;
  position?: { mode: "after_table" | "above"; row?: number | null };
  batch_id?: string;
}

export function useAddRow() {
  const client = useQueryClient();
  return useMutation<AddRowResult, ApiError, AddRowIn>({
    mutationFn: (body) => api.post<AddRowResult>("/sheets/add-row", body),
    onSuccess: (result, variables) => {
      client.setQueryData(qk.tab(variables.workbook_id, variables.sheet_id), result.tab);
      invalidateAfterWrite(client, variables.workbook_id, variables.sheet_id);
    },
  });
}

// --- admin ----------------------------------------------------------------------------------------

// The four readers below are admin-only, so every one of them takes the
// caller's role: a member skips the query rather than polling a 403 every 15 seconds.

export function useConnections(enabled = true) {
  return useQuery<Connections, ApiError>({
    ...list(qk.connections, () => api.get<Connections>("/admin/connections")),
    enabled,
  });
}

/**
 * The banner on every page. Its own route, readable by members, because the connection list
 * above is admin-only and a member would otherwise see no banner at all.
 */
export function useConnectionStatus(enabled = true) {
  return useQuery<ConnectionStatus, ApiError>({
    ...list(qk.connectionStatus, () => api.get<ConnectionStatus>("/admin/connections/status")),
    enabled,
  });
}

export function useAllowList(enabled = true) {
  return useQuery<AllowEntry[], ApiError>({
    ...list(qk.allowList, () => api.get<AllowEntry[]>("/admin/allow-list")),
    enabled,
  });
}

export function useAddAllowEntry() {
  const client = useQueryClient();
  return useMutation<AllowEntry, ApiError, { email: string; role?: "admin" | "member" }>({
    mutationFn: (body) => api.post<AllowEntry>("/admin/allow-list", body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: qk.allowList });
      void client.invalidateQueries({ queryKey: qk.activity });
    },
  });
}

export function useRemoveAllowEntry() {
  const client = useQueryClient();
  return useMutation<{ ok: boolean }, ApiError, string>({
    mutationFn: (email) => api.del(`/admin/allow-list/${encodeURIComponent(email)}`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: qk.allowList });
      void client.invalidateQueries({ queryKey: qk.activity });
    },
  });
}

export function useActivity(limit = 40, enabled = true) {
  return useQuery<ActivityEntry[], ApiError>({
    ...list(qk.activity, () => api.get<ActivityEntry[]>("/admin/activity", { limit })),
    enabled,
  });
}
