import { useState } from "react";
import { Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiUrl } from "@/api/client";
import { useActivity, useAddAllowEntry, useAllowList, useConnections, useRemoveAllowEntry } from "@/api/hooks";
import { fmtClock, fmtDate, shortName } from "@/lib/display";
import type { Me } from "@/api/types";

export function AdminPage({ me }: { me: Me }) {
  const isAdmin = me.is_admin;
  // The four readers are `require_admin` (Review 1, finding 28). A member is told so once, rather
  // than shown three lists that are empty because every poll is a 403.
  const connections = useConnections(isAdmin);
  const allowList = useAllowList(isAdmin);
  const activity = useActivity(40, isAdmin);
  const addEntry = useAddAllowEntry();
  const removeEntry = useRemoveAllowEntry();
  const [email, setEmail] = useState("");

  const add = async () => {
    const value = email.trim().toLowerCase();
    if (!value.includes("@")) return;
    try {
      await addEntry.mutateAsync({ email: value });
      setEmail("");
    } catch (error) {
      toast.message(error instanceof Error ? error.message : "Could not add that email");
    }
  };

  const intro = (
    <p className="text-[13px] text-muted-foreground">
      Everyone on the allow-list works on the same meetings, points and sheets, and sees each other's changes. Google is
      reached through the admin connections; the portal records who did what.
    </p>
  );

  // Screen review R2-04: a member used to get the three sections anyway - empty lists, a disabled
  // field, and a "Connect an account" link that `disabled` cannot disable on an anchor, which led
  // to a 403. For a member the notice is the page.
  if (!isAdmin) {
    return (
      <div className="mx-auto flex h-full min-h-0 w-full max-w-[960px] flex-col gap-8 overflow-y-auto">
        {intro}
        <div className="border px-3 py-2 text-[13px] font-medium" data-testid="admin-members-notice">
          Google connections, the allow-list and the activity log are admins only. Everything else in the portal is yours to
          use. Ask an admin if a connection needs reconnecting.
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex h-full min-h-0 w-full max-w-[960px] flex-col gap-8 overflow-y-auto">
      {intro}

      <section>
        <div className="mb-2 flex items-baseline gap-3">
          <h2 className="text-[15px] font-semibold">Google connections</h2>
          {connections.data?.warning && <span className="text-xs font-medium">{connections.data.warning}</span>}
          <Button size="sm" variant="outline" className="ml-auto h-8" asChild>
            <a href={apiUrl("/admin/connections/connect")}>Connect an account</a>
          </Button>
        </div>
        <ul className="divide-y border-y text-[13px]">
          {(connections.data?.connections ?? []).map((c) => (
            // R1-34: every row the same shape - who, then when and Reconnect, then the scopes on a
            // line of their own (a long scope list used to push the date to a second line on one
            // row and not the other).
            <li key={c.email} className="flex flex-col gap-1 py-2.5">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="font-medium">{c.name}</span>
                <span className="min-w-0 truncate text-muted-foreground">{c.email}</span>
                <span className={c.status === "ok" ? "ml-auto text-xs text-muted-foreground" : "ml-auto text-xs font-medium"}>
                  {c.status === "ok" ? `since ${fmtDate((c.connected_at ?? "").slice(0, 10))}` : "expired"}
                </span>
                <a className="text-xs underline underline-offset-2" href={apiUrl(`/admin/connections/connect?email=${encodeURIComponent(c.email)}`)}>
                  Reconnect
                </a>
              </div>
              <span className="text-xs text-muted-foreground">{c.scopes.join(", ")}</span>
            </li>
          ))}
          {!connections.isLoading && (connections.data?.connections ?? []).length === 0 && (
            <li className="py-2.5 text-xs text-muted-foreground">
              No Google account is connected yet.
            </li>
          )}
        </ul>
        <p className="mt-2 text-xs text-muted-foreground">
          Reads use the first healthy connection that can see the item. Sheets writes use the connection that connected that
          workbook. Tokens are encrypted at rest.
        </p>
      </section>

      <section>
        <div className="mb-2 flex items-baseline gap-3">
          <h2 className="text-[15px] font-semibold">Allow-list</h2>
          <span className="text-xs text-muted-foreground">{(allowList.data ?? []).length}</span>
        </div>
        <div className="mb-2 flex gap-2">
          <Input
            id="allow-email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="name@example.com"
            className="h-8 max-w-xs text-sm"
            onKeyDown={(e) => e.key === "Enter" && void add()}
          />
          <Button size="sm" variant="outline" className="h-8" onClick={() => void add()}>Add</Button>
        </div>
        <ul className="divide-y border-y text-[13px]">
          {(allowList.data ?? []).map((a) => (
            // R1-40: on a phone the email has the first line to itself and role and sign-in state
            // share the second ("not yet signed in" used to break over two lines beside it).
            <li key={a.email} className="flex items-center gap-3 py-2">
              <div className="flex min-w-0 flex-1 flex-col sm:flex-row sm:items-baseline sm:gap-3">
                <span className="truncate">{a.email}</span>
                <span className="whitespace-nowrap text-xs text-muted-foreground">
                  {a.role}{a.signed_in ? "" : " · not yet signed in"}
                </span>
              </div>
              <span className="hidden whitespace-nowrap text-xs text-muted-foreground sm:inline">
                added by {shortName(a.added_by)} · {fmtDate((a.added_at ?? "").slice(0, 10))}
              </span>
              <button
                className="text-muted-foreground hover:text-foreground disabled:opacity-30"
                aria-label={`Remove ${a.email}`}
                disabled={a.email === me.email}
                onClick={() => removeEntry.mutate(a.email)}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-muted-foreground">
          Sign-in is Google, restricted to example.com, then this list. Admins manage connections and the list; members do
          everything else.
        </p>
      </section>

      <section>
        <h2 className="mb-2 text-[15px] font-semibold">Activity</h2>
        <ul className="divide-y border-y text-[13px]">
          {(activity.data ?? []).slice(0, 12).map((a) => (
            <li key={a.id} className="flex gap-3 py-1.5">
              <span className="mono w-14 shrink-0 text-xs text-muted-foreground">{fmtClock(a.at)}</span>
              <span className="hidden w-40 shrink-0 truncate text-muted-foreground sm:inline" title={a.actor}>{shortName(a.actor)}</span>
              <span className="truncate">{a.text}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
