// One idempotency key per user intent, for the three routes that write to Google Sheets.
//
// Review 1, finding 9: the API takes a client `batch_id` on `transfers/execute`, `sheets/save` and
// `sheets/add-row`, writes the intent row before it calls Google, and answers a repeat of a
// finished id with the stored result. That only helps if the browser sends the *same* id when it
// tries again - a fresh uuid per attempt is a second write. So the id is minted once per press and
// held until the outcome is known:
//
//   the write landed        -> reset, the next press is a new intent
//   the server refused (4xx) -> reset; nothing was written, and the next press carries a different
//                               body (a clash resolved, "Send again" ticked), which the same id
//                               would be refused for anyway
//   no answer, or a 5xx     -> keep. Whether Google was called is unknown, and that is exactly the
//                               case the key exists for: pressing Save again replays instead of
//                               writing twice.

import { useCallback, useRef } from "react";
import { ApiError } from "@/api/client";

/** `crypto.randomUUID` everywhere it exists; the fallback is for a non-secure-context browser. */
export function newBatchId(): string {
  const webCrypto = globalThis.crypto;
  if (webCrypto && typeof webCrypto.randomUUID === "function") return webCrypto.randomUUID();
  const bytes = new Uint8Array(16);
  if (webCrypto && typeof webCrypto.getRandomValues === "function") webCrypto.getRandomValues(bytes);
  else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/**
 * True when the API gave a definite answer that nothing was written: any 4xx, including the 409s
 * this app raises on purpose. A transport failure (status 0) and a 5xx are *not* definite.
 */
export function isDefiniteRefusal(error: unknown): boolean {
  return error instanceof ApiError && error.status >= 400 && error.status < 500;
}

export interface BatchId {
  /** The id for this attempt: the same one until `reset`, so a retry cannot double-write. */
  take: () => string;
  reset: () => void;
  /** `take` again after this unless the failure leaves the outcome unknown. */
  settle: (error?: unknown) => void;
}

export function useBatchId(): BatchId {
  const held = useRef<string | null>(null);
  const take = useCallback(() => (held.current ??= newBatchId()), []);
  const reset = useCallback(() => {
    held.current = null;
  }, []);
  const settle = useCallback(
    (error?: unknown) => {
      if (error === undefined || isDefiniteRefusal(error)) reset();
    },
    [reset],
  );
  return { take, reset, settle };
}
