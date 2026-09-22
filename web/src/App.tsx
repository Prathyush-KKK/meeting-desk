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
import { ApiError } from "@/api/client";
import { useConnections, useMe, useMeetings } from "@/api/hooks";

type Page = "capture" | "sheets" | "admin";
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
  // Review 1, finding 28: `/admin/connections` is admin-only now. A member asking for it gets a
  // 403 every 15 s and no banner either way, so the question is only asked when the answer can
  // come back - which the role on `/auth/me` settles.
  const connections = useConnections(me.data?.is_admin === true);
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

  const go = useCallback(
    (s: WizardStep) => {
      if (s !== "meeting" && !meetingId) return;
      setStep(s);
    },
    [meetingId],
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
                const reachable = i === 0 || !!meetingId;
                return (
                  <li key={s.key} className="flex items-center">
                    <button
                      disabled={!reachable}
                      onClick={() => go(s.key)}
                      className={cn("px-1", on ? "text-foreground" : "text-muted-foreground", reachable && !on && "hover:text-foreground")}
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

      {connections.data?.banner && (
        <div className="shrink-0 border-b px-4 py-1.5 text-xs font-medium md:px-6" data-testid="connection-banner">{connections.data.banner}</div>
      )}

      <main className="min-h-0 flex-1 overflow-y-auto px-4 py-4 md:overflow-hidden md:px-6">
        {page === "capture" && step === "meeting" && (
          <MeetingStep
            selectedKey={selectedKey}
            onSelectKey={setSelectedKey}
            onContinue={(id) => {
              setMeetingId(id);
              setSelectedKey(id);
              setStep("notes");
            }}
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
      <Toaster position="bottom-right" />
    </div>
  );
}
