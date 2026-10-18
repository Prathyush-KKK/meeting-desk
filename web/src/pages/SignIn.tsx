import { Button } from "@/components/ui/button";
import { apiUrl } from "@/api/client";

/** 401: one line and a link to the API's Google login route. */
export function SignIn() {
  return (
    <Shell title="Meeting Desk">
      <p className="text-[13px] text-muted-foreground">Sign in with your Google account to continue.</p>
      <Button className="mt-4 h-9" asChild>
        <a href={apiUrl("/auth/login")}>Sign in with Google</a>
      </Button>
    </Shell>
  );
}

/** 403: the account signed in but is not allow-listed. The message names who to ask. */
export function NotAllowed({ message }: { message: string }) {
  return (
    <Shell title="Not on the list">
      <p className="max-w-[46ch] text-[13px] text-muted-foreground">
        {message || "This Google account is not on the Meeting Desk allow-list. Ask an admin to add it."}
      </p>
      <a className="mt-4 text-[13px] underline underline-offset-2" href={apiUrl("/auth/login")}>
        Try another account
      </a>
    </Shell>
  );
}

function Shell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex h-full min-h-0 flex-col items-center justify-center px-6 text-center">
      <h1 className="text-[15px] font-semibold">{title}</h1>
      <div className="mt-2 flex flex-col items-center">{children}</div>
    </div>
  );
}
