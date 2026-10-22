import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { PointRow, SELECT_CLASS, ROW_GRID } from "@/components/PointRow";
import { TransferLines } from "@/components/History";
import { cn } from "@/lib/utils";
import { useElapsedSeconds } from "@/lib/elapsed";
import { download, exportName, pointsToCsv, pointsToGithubMarkdown, pointsToMarkdown } from "@/lib/export";
import { KIND_ORDER, KIND_TITLE, STATUSES, STATUS_LABEL, clip, fmtClock, mergeWorkstreams } from "@/lib/display";
import {
  useAddPoint,
  useBulkPatchPoints,
  useCopyPointsAsText,
  useDeferPoints,
  useDeletePoint,
  useExtract,
  useExtractions,
  useMeetingTransfers,
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
  const [showTransferred, setShowTransferred] = useState(false);
  // Asked for only once opened, like the deferred list.
  const transfers = useMeetingTransfers(showTransferred ? meetingId : null);

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
  // A failed run is kept on record now. Newest on top and failed: say so, or an empty page after
  // Extract reads as "the model found nothing".
  const newest = extractions.data?.[0];
  const failed = newest?.status === "error" ? newest : null;
  const elapsed = useElapsedSeconds(extract.isPending);

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
    let text: string;
    try {
      text = `${meeting.title} · ${meeting.date}\n\n${(await copyText.mutateAsync(points.map((p) => p.id))).text}`;
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not build the text");
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      toast.success("Copied");
    } catch {
      // No clipboard (an insecure origin, a blocked permission): the same text as a file instead.
      download(text, `${exportName(meeting)}.txt`, "text/plain;charset=utf-8");
      toast.message("Clipboard is blocked here, so the text was downloaded instead");
    }
  };

  const exportAs = (format: string) => {
    if (!points.length) return;
    if (format === "github" && points.some((p) => p.kind === "action")) download(pointsToGithubMarkdown(points, meeting), `${exportName(meeting)}.github.md`, "text/markdown;charset=utf-8");
    if (format === "md") download(pointsToMarkdown(points, meeting), `${exportName(meeting)}.md`, "text/markdown;charset=utf-8");
    if (format === "csv") download(pointsToCsv(points, meeting), `${exportName(meeting)}.csv`, "text/csv;charset=utf-8");
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        {/* The meeting's latest extraction, not a fixed model name whatever answered; nothing when
            the points came another way. */}
        {lastExtraction && (
          <span className="hidden md:inline" data-testid="extracted-with">
            {/* The fake has no model worth naming ("rule-based · the local rule-based fake"). */}
            {lastExtraction.provider === "fake" ? (
              "Extracted by the local rule-based fake"
            ) : (
              <>Extracted with <span className="mono text-foreground">{lastExtraction.model}</span> · {providerLabel(lastExtraction)}</>
            )}
          </span>
        )}
        <span>{editor.pending ? `saving ${editor.pending}…` : editor.savedAt ? `saved ${fmtClock(editor.savedAt)}` : "autosaves"}</span>
        {failed && (
          <span className="font-medium text-foreground" data-testid="extraction-error" title={failed.error ?? undefined}>
            Last extraction failed{failed.error ? `: ${clip(failed.error, 200)}` : "."}
          </span>
        )}
        <button
          className="underline-offset-2 hover:underline"
          disabled={extract.isPending}
          onClick={async () => {
            try {
              const result = await extract.mutateAsync();
              toast.success(result.points.length ? `${result.points.length} new points` : "Nothing new");
            } catch (error) {
              toast.error(error instanceof Error ? error.message : "Extraction failed");
            }
          }}
        >
          {extract.isPending ? `Extracting… ${elapsed}s` : "Re-extract"}
        </button>
        <button
          className={cn("underline-offset-2 hover:underline", showDeferred && "text-foreground")}
          onClick={() => setShowDeferred((v) => !v)}
        >
          {showDeferred ? "Hide deferred" : "See deferred"}
        </button>
        <button
          className={cn("underline-offset-2 hover:underline", showTransferred && "text-foreground")}
          onClick={() => setShowTransferred((v) => !v)}
        >
          {showTransferred ? "Hide transferred" : "See transferred"}
        </button>
        {/* On a phone the six bulk controls are two rows of three - count, Assign to, Set status;
            Apply, Defer, Add point. As one strip they scrolled sideways and Defer was cut to "D";
            nothing on a phone scrolls sideways but a grid in its own box. */}
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

        {/* Read-only: a transferred point has left this tool; the sheet is where it is edited. */}
        {showTransferred && (
          <div data-testid="transferred">
            <div className="px-2 pb-1 pt-4 text-[11px] uppercase tracking-wide text-muted-foreground">
              Transferred · {(transfers.data ?? []).length}
            </div>
            <TransferLines
              className="px-2 pb-2"
              transfers={transfers.data ?? []}
              loading={transfers.isLoading}
              empty="Nothing transferred from this meeting."
            />
          </div>
        )}
      </div>

      {/* On a phone the four buttons are a 2 x 2 block with Transfer bottom right; the row
          used to wrap and leave Transfer alone on a second line at the left. */}
      <div className="grid grid-cols-2 gap-2 md:flex md:flex-wrap md:items-center" data-testid="points-footer">
        <Button variant="outline" className="h-9" onClick={onBack}>Back</Button>
        <Button variant="outline" className="h-9" onClick={() => void copy()}>Copy as text</Button>
        <select
          className={cn(SELECT_CLASS, "col-span-2 h-9 md:col-span-1")}
          value=""
          disabled={!points.length}
          onChange={(e) => exportAs(e.target.value)}
          aria-label="Export points"
          data-testid="export-points"
        >
          <option value="">Export…</option>
          <option value="md">Markdown (.md)</option>
          <option value="csv">CSV (.csv)</option>
          <option value="github" disabled={!points.some((p) => p.kind === "action")}>GitHub Issues (.md)</option>
        </select>
        <span className="hidden text-xs text-muted-foreground md:inline">After transfer, points leave this tool.</span>
        <Button variant="outline" className="h-9 md:ml-auto" onClick={onKeep}>Keep here</Button>
        <Button className="h-9" disabled={!selected.length} onClick={() => onTransfer(selected.map((p) => p.id))}>
          {selected.length ? `Transfer ${selected.length}` : "Transfer"}
        </Button>
      </div>
    </div>
  );
}

const PROVIDER: Record<string, string> = {
  vertex: "Vertex AI",
  bedrock: "Amazon Bedrock",
  openai: "an OpenAI-compatible endpoint",
  anthropic: "the Anthropic API",
  fake: "the local rule-based fake",
};

/** "Vertex AI asia-south1", or "Amazon Bedrock ap-south-1, after Vertex AI failed". */
export function providerLabel(e: { provider: string; region: string | null; fallback_from: string | null }): string {
  const name = PROVIDER[e.provider] ?? e.provider;
  const region = e.region && e.region !== "local" ? ` ${e.region}` : "";
  const fallback = e.fallback_from ? `, after ${PROVIDER[e.fallback_from] ?? e.fallback_from} failed` : "";
  return `${name}${region}${fallback}`;
}
