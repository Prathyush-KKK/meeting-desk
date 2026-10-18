import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Toaster } from "@/components/ui/sonner";
import { MeetingStep } from "@/pages/MeetingStep";
import { NotesStep } from "@/pages/NotesStep";
import { PointsStep } from "@/pages/PointsStep";
import { TransferStep } from "@/pages/TransferStep";
import { SheetsPage } from "@/pages/SheetsPage";
import { AdminPage } from "@/pages/AdminPage";
import { NotAllowed, SignIn } from "@/pages/SignIn";
import { cn } from "@/lib/utils";
import { useNarrow } from "@/lib/overlay";
import { ApiError, apiUrl } from "@/api/client";
import { useConnectionStatus, useMe, useMeetings } from "@/api/hooks";
import { configureDisplay } from "@/lib/display";

type Page = "capture" | "sheets" | "admin";

/**
 * Bottom right is where every step keeps its primary button (Continue, Transfer, Insert and
 * write, Save to Sheet), and a toast with Undo would sit on it for ten seconds. From
 * 768 px the bottom centre only ever covers hint text; on a phone the bottom is all buttons, so the
 * toast goes to the top, over the page tabs for as long as it lasts.
 */
export function toastPosition(narrow: boolean): "top-center" | "bottom-center" {
  return narrow ? "top-center" : "bottom-center";
}
type WizardStep = "meeting" | "notes" | "points" | "transfer";

const STEPS: { key: WizardStep; label: string }[] = [
  { key: "meeting", label: "Meeting" },
  { key: "notes", label: "Notes" },
  { key: "points", label: "Points" },
  { key: "transfer", label: "Transfer" },
];

/** The current place is in the URL, so a reload or a lost phone session comes back where it was. */
function readUrl() {
  const params = new URLSearchParams(window.location.search);
  const page = params.get("page");
  const step = params.get("step");
  return {
    page: (["capture", "sheets", "admin"].includes(page ?? "") ? page : "capture") as Page,
    step: (STEPS.some((s) => s.key === step) ? step : "meeting") as WizardStep,
    meetingId: params.get("meeting"),
    wb: params.get("wb"),
    tab: params.get("tab"),
  };
}

export default function App() {
  const me = useMe();
  // Before anything below renders a time or a workstream list: the workspace's zone and names.
  if (me.data) configureDisplay(me.data);
  const narrow = useNarrow();
  const initial = readUrl();
  const [page, setPage] = useState<Page>(initial.page);
  const [step, setStep] = useState<WizardStep>(initial.step);
  const [meetingId, setMeetingId] = useState<string | null>(initial.meetingId);
  const [selectedKey, setSelectedKey] = useState<string | null>(initial.meetingId);
  const [transferIds, setTransferIds] = useState<string[]>([]);
  const [sheetSel, setSheetSel] = useState<{ wb: string; tab: string } | null>(
    initial.wb && initial.tab ? { wb: initial.wb, tab: initial.tab } : null,
  );

  const meetings = useMeetings();
  // `/admin/connections` is admin-only, so the banner cannot come from it or a member would see
  // none. The banner has its own route that anyone signed in may read; it is
  // asked for once `/auth/me` has answered.
  const status = useConnectionStatus(!!me.data);
  const items = meetings.data?.items ?? [];
  const meeting = meetingId ? (items.find((m) => m.id === meetingId) ?? null) : null;
  const activePoints = items.reduce((total, m) => total + (m.points_count || 0), 0);
  const stepIndex = STEPS.findIndex((s) => s.key === step);

  useEffect(() => {
    const params = new URLSearchParams();
    params.set("page", page);
    if (page === "capture") {
      params.set("step", step);
      if (meetingId) params.set("meeting", meetingId);
    }
    if (page === "sheets" && sheetSel) {
      params.set("wb", sheetSel.wb);
      params.set("tab", sheetSel.tab);
    }
    const next = `${window.location.pathname}?${params.toString()}`;
    if (next !== `${window.location.pathname}${window.location.search}`) {
      window.history.replaceState(null, "", next);
    }
  }, [page, step, meetingId, sheetSel]);

  /** A saved meeting straight at a step, from its card or its detail panel, whatever its date. */
  const openAt = useCallback(
    (id: string, s: "notes" | "points") => {
      // Picked points belong to the meeting they were picked on.
      if (id !== meetingId) setTransferIds([]);
      setMeetingId(id);
      setSelectedKey(id);
      setStep(s);
    },
    [meetingId],
  );

  // On Step 1 the step bar follows the highlighted card when it is a saved meeting: it used to need
  // a Continue first (or the meeting from an earlier visit, kept in the URL), so Notes and Points
  // stayed shut, or opened a meeting other than the one highlighted.
  const selectedSaved = step === "meeting" && selectedKey && items.some((m) => m.id === selectedKey) ? selectedKey : null;
  const target = selectedSaved ?? meetingId;
  // Transfer carries the points picked on Step 3, so it stays with the meeting they came from.
  const reachable = useCallback(
    (s: WizardStep) => s === "meeting" || (s === "transfer" ? !!meetingId && target === meetingId : !!target),
    [meetingId, target],
  );

  const go = useCallback(
    (s: WizardStep) => {
      if (!reachable(s)) return;
      if ((s === "notes" || s === "points") && target && target !== meetingId) openAt(target, s);
      else setStep(s);
    },
    [reachable, target, meetingId, openAt],
  );

  if (me.isLoading) return <div className="p-6 text-sm text-muted-foreground">Loading…</div>;
  if (me.error instanceof ApiError && me.error.isAuth) return <SignIn />;
  if (me.error instanceof ApiError && me.error.isForbidden) return <NotAllowed message={me.error.message} />;
  if (!me.data) return <div className="p-6 text-sm font-medium">{me.error?.message ?? "The API is not reachable."}</div>;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="shrink-0 border-b px-4 md:px-6" style={{ paddingTop: "env(safe-area-inset-top, 0px)" }}>
        <div className="flex h-12 items-center gap-4 md:gap-6">
          <span className="text-[14px] font-semibold">Meeting Desk</span>
          <nav className="flex items-center gap-3 text-[13px]">
            {(["capture", "sheets", "admin"] as Page[]).map((p) => (
              <button
                key={p}
                onClick={() => setPage(p)}
                className={cn("h-12 border-b-2 capitalize", page === p ? "border-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}
              >
                {p}
                {p === "capture" && activePoints > 0 && <span className="ml-1 text-xs text-muted-foreground">{activePoints}</span>}
              </button>
            ))}
          </nav>
          <span className="ml-auto hidden truncate text-xs text-muted-foreground sm:inline">{me.data.email}</span>
        </div>
        {page === "capture" && (
          <div className="flex h-9 items-center gap-1 text-[13px]">
            <ol className="hidden items-center gap-1 md:flex">
              {STEPS.map((s, i) => {
                const on = i === stepIndex;
                const canGo = reachable(s.key);
                return (
                  <li key={s.key} className="flex items-center">
                    <button
                      disabled={!canGo}
                      onClick={() => go(s.key)}
                      className={cn("px-1", on ? "text-foreground" : "text-muted-foreground", canGo && !on && "hover:text-foreground")}
                    >
                      <span className="mono mr-1.5 text-xs">{i + 1}</span>{s.label}
                    </button>
                    {i < STEPS.length - 1 && <span className="mx-2 text-muted-foreground">/</span>}
                  </li>
                );
              })}
            </ol>
            <span className="text-muted-foreground md:hidden">Step {stepIndex + 1} of 4 · {STEPS[stepIndex].label}</span>
            {meeting && <span data-testid="current-meeting" className="ml-auto truncate text-xs text-muted-foreground">{meeting.title || "Untitled"}</span>}
          </div>
        )}
      </header>

      {status.data?.banner && (
        <div className="shrink-0 border-b px-4 py-1.5 text-xs font-medium md:px-6" data-testid="connection-banner">{status.data.banner}</div>
      )}
      {!status.data?.banner && status.data?.first_run && (
        <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b px-4 py-1.5 text-xs md:px-6" data-testid="first-run-banner">
          <span>{status.data.first_run_notice}</span>
          {status.data.can_connect && (
            <a className="font-medium underline underline-offset-2" href={apiUrl("/admin/connections/connect?next=/")}>Connect Google account</a>
          )}
        </div>
      )}

      <main className="min-h-0 flex-1 overflow-y-auto px-4 py-4 md:overflow-hidden md:px-6">
        {page === "capture" && step === "meeting" && (
          <MeetingStep
            selectedKey={selectedKey}
            onSelectKey={setSelectedKey}
            onContinue={(id) => openAt(id, "notes")}
            onOpenStep={openAt}
          />
        )}
        {page === "capture" && step === "notes" && meeting && (
          <NotesStep meeting={meeting} onBack={() => setStep("meeting")} onExtracted={() => setStep("points")} />
        )}
        {page === "capture" && step === "points" && meeting && (
          <PointsStep
            meeting={meeting}
            onBack={() => setStep("notes")}
            onTransfer={(ids) => { setTransferIds(ids); setStep("transfer"); }}
            onKeep={() => { toast.success("Kept"); setStep("meeting"); }}
          />
        )}
        {page === "capture" && step === "transfer" && meeting && (
          <TransferStep
            meeting={meeting}
            pointIds={transferIds}
            onBack={() => setStep("points")}
            onDone={(wb, tab) => {
              setSheetSel({ wb, tab });
              setPage("sheets");
              setStep("meeting");
              setTransferIds([]);
            }}
          />
        )}
        {page === "capture" && step !== "meeting" && !meeting && (
          <div className="p-6 text-sm text-muted-foreground">
            {meetings.isLoading ? "Loading…" : "Pick a meeting first."}
          </div>
        )}
        {page === "sheets" && <SheetsPage selection={sheetSel} onSelect={setSheetSel} me={me.data} />}
        {page === "admin" && <AdminPage me={me.data} />}
      </main>
      <Toaster position={toastPosition(narrow)} />
    </div>
  );
}
