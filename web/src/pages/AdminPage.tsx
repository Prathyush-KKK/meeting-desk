import { useState } from "react";
import { Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiUrl } from "@/api/client";
import { useActivity, useAddAllowEntry, useAllowList, useConnections, useRemoveAllowEntry } from "@/api/hooks";
import { fmtClock, shortName } from "@/lib/display";
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

  return (
    <div className="mx-auto flex h-full min-h-0 w-full max-w-[960px] flex-col gap-8 overflow-y-auto">
      <p className="text-[13px] text-muted-foreground">
        Everyone on the allow-list works on the same meetings, points and sheets, and sees each other's changes. Google is
        reached through the admin connections below; the portal records who did what.
      </p>

      {!isAdmin && (
        <div className="border px-3 py-2 text-[13px] font-medium" data-testid="admin-members-notice">
          Google connections, the allow-list and the activity log are admins only. Everything else in the portal is yours to
          use. Ask an admin if a connection needs reconnecting.
        </div>
      )}

      {connections.data?.banner && (
        <div className="border px-3 py-2 text-[13px] font-medium">{connections.data.banner}</div>
      )}

      <section>
        <div className="mb-2 flex items-baseline gap-3">
          <h2 className="text-[15px] font-semibold">Google connections</h2>
          {connections.data?.warning && <span className="text-xs font-medium">{connections.data.warning}</span>}
          <Button size="sm" variant="outline" className="ml-auto h-8" disabled={!isAdmin} asChild>
            <a href={apiUrl("/admin/connections/connect")}>Connect an account</a>
          </Button>
        </div>
        <ul className="divide-y border-y text-[13px]">
          {(connections.data?.connections ?? []).map((c) => (
            <li key={c.email} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5">
              <span className="font-medium">{c.name}</span>
              <span className="text-muted-foreground">{c.email}</span>
              <span className="w-full text-xs text-muted-foreground sm:w-auto">{c.scopes.join(", ")}</span>
              <span className="ml-auto text-xs text-muted-foreground">
                {c.status === "ok" ? `since ${(c.connected_at ?? "").slice(0, 10)}` : "expired"}
              </span>
              <a className="text-xs underline-offset-2 hover:underline" href={apiUrl(`/admin/connections/connect?email=${encodeURIComponent(c.email)}`)}>
                Reconnect
              </a>
            </li>
          ))}
          {!connections.isLoading && (connections.data?.connections ?? []).length === 0 && (
            <li className="py-2.5 text-xs text-muted-foreground">
              {isAdmin ? "No Google account is connected yet." : "Only admins can read the connection list."}
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
            placeholder="name@simpleo.ai"
            className="h-8 max-w-xs text-sm"
            disabled={!isAdmin}
            onKeyDown={(e) => e.key === "Enter" && void add()}
          />
          <Button size="sm" variant="outline" className="h-8" onClick={() => void add()} disabled={!isAdmin}>Add</Button>
        </div>
        <ul className="divide-y border-y text-[13px]">
          {(allowList.data ?? []).map((a) => (
            <li key={a.email} className="flex items-center gap-3 py-2">
              <span className="truncate">{a.email}</span>
              <span className="text-xs text-muted-foreground">{a.role}</span>
              {!a.signed_in && <span className="text-xs text-muted-foreground">not yet signed in</span>}
              <span className="ml-auto hidden text-xs text-muted-foreground sm:inline">
                by {shortName(a.added_by)}@ · {(a.added_at ?? "").slice(0, 10)}
              </span>
              <button
                className="text-muted-foreground hover:text-foreground disabled:opacity-30"
                aria-label="Remove"
                disabled={!isAdmin || a.email === me.email}
                onClick={() => removeEntry.mutate(a.email)}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-muted-foreground">
          Sign-in is Google, restricted to simpleo.ai, then this list. Admins manage connections and the list; members do
          everything else.
        </p>
      </section>

      <section>
        <h2 className="mb-2 text-[15px] font-semibold">Activity</h2>
        <ul className="divide-y border-y text-[13px]">
          {(activity.data ?? []).slice(0, 12).map((a) => (
            <li key={a.id} className="flex gap-3 py-1.5">
              <span className="mono w-14 shrink-0 text-xs text-muted-foreground">{fmtClock(a.at)}</span>
              <span className="hidden w-40 shrink-0 truncate text-muted-foreground sm:inline">{a.actor}</span>
              <span className="truncate">{a.text}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
