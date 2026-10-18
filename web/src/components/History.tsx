import { clip, fmtStamp, shortName, transferSheet } from "@/lib/display";
import { cn } from "@/lib/utils";
import type { ExtractionRecord, Transfer } from "@/api/types";

// A meeting's history, read-only: the extraction runs and what went to a sheet. Step 1's detail
// panel and Step 3's "See transferred" both show it, so a past meeting is more than a title.

const EMPTY = "text-xs text-muted-foreground";

export function ExtractionLines({ runs, loading, className }: { runs: ExtractionRecord[]; loading?: boolean; className?: string }) {
  if (loading) return <div className={cn(EMPTY, className)}>Loading…</div>;
  if (!runs.length) return <div className={cn(EMPTY, className)}>No extraction yet.</div>;
  return (
    <ul className={cn("space-y-1", className)}>
      {runs.map((e) => (
        <li key={e.id} data-testid="extraction-line" data-status={e.status} className="text-xs text-muted-foreground">
          {e.at && <span className="mono">{fmtStamp(e.at)} · </span>}
          {/* The fake has no model worth naming. */}
          {e.provider === "fake" ? "rule-based fake" : <span className="mono text-foreground">{e.model}</span>}
          {` · ${e.status}`}
          {e.status === "done" && ` · ${e.created_points ?? 0} new`}
          {e.status === "error" && e.error && (
            <>
              {" · "}
              <span className="text-foreground" title={e.error}>{clip(e.error, 160)}</span>
            </>
          )}
        </li>
      ))}
    </ul>
  );
}

export function TransferLines({
  transfers,
  empty,
  loading,
  className,
}: {
  transfers: Transfer[];
  empty: string;
  loading?: boolean;
  className?: string;
}) {
  if (loading) return <div className={cn(EMPTY, className)}>Loading…</div>;
  if (!transfers.length) return <div className={cn(EMPTY, className)}>{empty}</div>;
  return (
    <ul className={cn("space-y-1", className)}>
      {transfers.map((t) => (
        <li key={t.id} data-testid="transfer-line" className="text-[13px]">
          <span className={cn(t.undone_at && "text-muted-foreground")}>{t.point_text}</span>
          <span className="text-xs text-muted-foreground">
            {` → ${transferSheet(t)} · ${fmtStamp(t.at)} · ${shortName(t.actor)}`}
            {t.undone_at && " · undone"}
          </span>
        </li>
      ))}
    </ul>
  );
}
