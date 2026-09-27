import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { PointRow, SELECT_CLASS, ROW_GRID } from "@/components/PointRow";
import { cn } from "@/lib/utils";
import { KIND_ORDER, KIND_TITLE, STATUSES, STATUS_LABEL, fmtClock, mergeWorkstreams } from "@/lib/display";
import {
  useAddPoint,
  useBulkPatchPoints,
  useCopyPointsAsText,
  useDeferPoints,
  useDeletePoint,
  useExtract,
  useExtractions,
  usePointEditor,
  usePoints,
  useRestorePoint,
} from "@/api/hooks";
import type { MeetingItem, Point } from "@/api/types";

interface Props {
  meeting: MeetingItem;
  onBack: () => void;
  onTransfer: (pointIds: string[]) => void;
  onKeep: () => void;
}

export function PointsStep({ meeting, onBack, onTransfer, onKeep }: Props) {
  const meetingId = meeting.id!;
  const active = usePoints(meetingId, "active");
  const [showDeferred, setShowDeferred] = useState(false);
  const deferred = usePoints(meetingId, "deferred", showDeferred);

  const editor = usePointEditor(meetingId, "active");
  const bulk = useBulkPatchPoints(meetingId, "active");
  const defer = useDeferPoints();
  const restore = useRestorePoint();
  const remove = useDeletePoint();
  const addPoint = useAddPoint(meetingId);
  const copyText = useCopyPointsAsText();
  const extract = useExtract(meetingId);
  const extractions = useExtractions(meetingId);
  const lastExtraction = extractions.data?.find((e) => e.status === "done") ?? null;

  const [bulkOwner, setBulkOwner] = useState("");
  const [bulkStatus, setBulkStatus] = useState("");

  const points = editor.merge(active.data ?? []);
  const selected = points.filter((p) => p.selected);
  const owners = useMemo(
    () => Array.from(new Set([...meeting.attendees.map((a) => a.name || a.email), "product"])).filter(Boolean),
    [meeting.attendees],
  );
  const workstreams = useMemo(() => mergeWorkstreams([meeting.workstream, ...points.map((p) => p.workstream)]), [meeting.workstream, points]);
  const allSel = points.length > 0 && points.every((p) => p.selected);

  const removeWithUndo = async (point: Point) => {
    const result = await remove.mutateAsync(point.id);
    toast("Point removed", {
      description: "10 seconds to undo; recoverable for 30 days.",
      duration: 10_000,
      action: { label: "Undo", onClick: () => restore.mutate(result.id) },
    });
  };

  const deferOne = async (point: Point) => {
    await defer.mutateAsync([point.id]);
    toast("Deferred", { description: "It is behind “See deferred”.", action: { label: "Undo", onClick: () => restore.mutate(point.id) } });
  };

  const applyBulk = () => {
    if (!selected.length) return;
    bulk.mutate({
      ids: selected.map((p) => p.id),
      patch: { ...(bulkOwner ? { owner_text: bulkOwner } : {}), ...(bulkStatus ? { status: bulkStatus } : {}) },
    });
    setBulkOwner("");
    setBulkStatus("");
  };

  const copy = async () => {
    try {
      const { text } = await copyText.mutateAsync(points.map((p) => p.id));
      await navigator.clipboard.writeText(`${meeting.title} · ${meeting.date}\n\n${text}`);
      toast.success("Copied");
    } catch {
      toast.message("Clipboard is blocked here; the text is on the server route /points/copy-text");
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        {/* R1-11: this was a fixed "gemini-2.5-flash · Vertex AI asia-south1" whatever answered.
            It is the meeting's latest extraction now, and nothing when the points came another way. */}
        {lastExtraction && (
          <span className="hidden md:inline" data-testid="extracted-with">
            {/* R2-02: the fake has no model worth naming ("rule-based · the local rule-based fake"). */}
            {lastExtraction.provider === "fake" ? (
              "Extracted by the local rule-based fake"
            ) : (
              <>Extracted with <span className="mono text-foreground">{lastExtraction.model}</span> · {providerLabel(lastExtraction)}</>
            )}
          </span>
        )}
        <span>{editor.pending ? `saving ${editor.pending}…` : editor.savedAt ? `saved ${fmtClock(editor.savedAt)}` : "autosaves"}</span>
        <button
          className="underline-offset-2 hover:underline"
          disabled={extract.isPending}
          onClick={async () => {
            const result = await extract.mutateAsync();
            toast.success(result.points.length ? `${result.points.length} new points` : "Nothing new");
          }}
        >
          Re-extract
        </button>
        <button
          className={cn("underline-offset-2 hover:underline", showDeferred && "text-foreground")}
          onClick={() => setShowDeferred((v) => !v)}
        >
          {showDeferred ? "Hide deferred" : "See deferred"}
        </button>
        {/* R4-02: on a phone the six bulk controls are two rows of three - count, Assign to, Set
            status; Apply, Defer, Add point. Round 2 made them one strip that scrolled sideways (R2-05)
            and Defer was cut to "D"; nothing on a phone scrolls sideways but a grid in its own box. */}
        <div className="grid w-full grid-cols-3 items-center gap-2 md:ml-auto md:flex md:w-auto md:flex-wrap" data-testid="bulk-bar">
          <span>{selected.length} selected</span>
          <select className={SELECT_CLASS} value={bulkOwner} onChange={(e) => setBulkOwner(e.target.value)} aria-label="Assign selected to">
            <option value="">Assign to</option>
            {owners.map((o) => <option key={o}>{o}</option>)}
          </select>
          <select className={SELECT_CLASS} value={bulkStatus} onChange={(e) => setBulkStatus(e.target.value)} aria-label="Set status of selected">
            <option value="">Set status</option>
            {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
          </select>
          <Button size="sm" variant="outline" className="h-8" disabled={!selected.length || (!bulkOwner && !bulkStatus)} onClick={applyBulk}>Apply</Button>
          <Button
            size="sm"
            variant="outline"
            className="h-8"
            disabled={!selected.length}
            onClick={async () => {
              const ids = selected.map((p) => p.id);
              await defer.mutateAsync(ids);
              toast.success(`Deferred ${ids.length}`);
            }}
          >
            Defer
          </Button>
          <Button size="sm" variant="outline" className="h-8" onClick={() => addPoint.mutate({ text: "", workstream: meeting.workstream })}>Add point</Button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto border-y">
        <div className={cn("hidden items-center gap-2 border-b bg-secondary px-2 py-1.5 text-[11px] uppercase tracking-wide text-muted-foreground md:grid", ROW_GRID)}>
          <Checkbox
            checked={allSel}
            onCheckedChange={(v) => bulk.mutate({ ids: points.map((p) => p.id), patch: { selected: !!v } })}
            aria-label="Select all"
          />
          <span>Kind</span><span>Point</span><span>Owner</span><span>Due</span><span>Status</span><span>Workstream</span><span aria-hidden="true" />
        </div>
        {active.isLoading && <div className="p-6 text-center text-xs text-muted-foreground">Loading…</div>}
        {!active.isLoading && points.length === 0 && <div className="p-6 text-center text-xs text-muted-foreground">No points yet.</div>}
        {KIND_ORDER.map((k) => {
          const ps = points.filter((p) => p.kind === k);
          if (!ps.length) return null;
          return (
            <div key={k}>
              <div className="px-2 pb-1 pt-3 text-[11px] uppercase tracking-wide text-muted-foreground">{KIND_TITLE[k]} · {ps.length}</div>
              {ps.map((p) => (
                <PointRow
                  key={p.id}
                  point={p}
                  owners={owners}
                  workstreams={workstreams}
                  onPatch={(body) => editor.edit(p.id, body)}
                  onDefer={() => void deferOne(p)}
                  onRestore={() => restore.mutate(p.id)}
                  onRemove={() => void removeWithUndo(p)}
                />
              ))}
            </div>
          );
        })}

        {showDeferred && (
          <div>
            <div className="px-2 pb-1 pt-4 text-[11px] uppercase tracking-wide text-muted-foreground">
              Deferred · {(deferred.data ?? []).length}
            </div>
            {(deferred.data ?? []).length === 0 && (
              <div className="px-2 pb-2 text-xs text-muted-foreground">Nothing deferred on this meeting.</div>
            )}
            {(deferred.data ?? []).map((p) => (
              <PointRow
                key={p.id}
                point={p}
                owners={owners}
                workstreams={workstreams}
                onPatch={() => undefined}
                onDefer={() => undefined}
                onRestore={() => restore.mutate(p.id)}
                onRemove={() => void removeWithUndo(p)}
                onTransfer={() => onTransfer([p.id])}
              />
            ))}
          </div>
        )}
      </div>

      {/* R1-10: on a phone the four buttons are a 2 x 2 block with Transfer bottom right; the row
          used to wrap and leave Transfer alone on a second line at the left. */}
      <div className="grid grid-cols-2 gap-2 md:flex md:flex-wrap md:items-center" data-testid="points-footer">
        <Button variant="outline" className="h-9" onClick={onBack}>Back</Button>
        <Button variant="outline" className="h-9" onClick={() => void copy()}>Copy as text</Button>
        <span className="hidden text-xs text-muted-foreground md:inline">After transfer, points leave this tool.</span>
        <Button variant="outline" className="h-9 md:ml-auto" onClick={onKeep}>Keep here</Button>
        <Button className="h-9" disabled={!selected.length} onClick={() => onTransfer(selected.map((p) => p.id))}>
          {selected.length ? `Transfer ${selected.length}` : "Transfer"}
        </Button>
      </div>
    </div>
  );
}

const PROVIDER: Record<string, string> = { vertex: "Vertex AI", bedrock: "Amazon Bedrock", fake: "the local rule-based fake" };

/** "Vertex AI asia-south1", or "Amazon Bedrock ap-south-1, after Vertex AI failed". */
export function providerLabel(e: { provider: string; region: string | null; fallback_from: string | null }): string {
  const name = PROVIDER[e.provider] ?? e.provider;
  const region = e.region && e.region !== "local" ? ` ${e.region}` : "";
  const fallback = e.fallback_from ? `, after ${PROVIDER[e.fallback_from] ?? e.fallback_from} failed` : "";
  return `${name}${region}${fallback}`;
}
