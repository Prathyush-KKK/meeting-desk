import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { useConnectWorkbook } from "@/api/hooks";
import type { ConnectedWorkbook } from "@/api/types";

/**
 * A Google Sheets URL and Connect. The Sheets sidebar, the Sheets page's empty state and the
 * Transfer step's prerequisites all use this one, so connecting reads the same wherever it is
 * offered (the empty states used to point somewhere else instead).
 */
export function ConnectWorkbook({
  className,
  onConnected,
  autoFocus,
}: {
  className?: string;
  onConnected?: (workbook: ConnectedWorkbook) => void;
  autoFocus?: boolean;
}) {
  const connect = useConnectWorkbook();
  const [url, setUrl] = useState("");

  const run = async () => {
    try {
      const result = await connect.mutateAsync(url.trim());
      setUrl("");
      toast.success(`Connected ${result.name}`);
      if (result.share_request) toast.message(result.share_request, { duration: 12_000 });
      onConnected?.(result);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not connect that workbook");
    }
  };

  return (
    <form
      className={cn("flex gap-2", className)}
      onSubmit={(e) => {
        e.preventDefault();
        if (url.trim()) void run();
      }}
    >
      <Input
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="Google Sheets URL"
        aria-label="Google Sheets URL"
        className="h-8 text-xs"
        autoFocus={autoFocus}
      />
      <Button type="submit" size="sm" variant="outline" className="h-8" disabled={!url.trim() || connect.isPending}>
        Connect
      </Button>
    </form>
  );
}
