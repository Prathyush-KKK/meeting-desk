import { useEffect, useState } from "react";

/**
 * Whole seconds since `active` went true, ticking once a second; 0 while inactive. An extraction on
 * Gemma 4 via Bedrock takes one to two minutes, and a bare "Extracting…" for that long reads as
 * stuck. Measured off the clock rather than counted, so a throttled background tab still reads
 * right when it comes back.
 */
export function useElapsedSeconds(active: boolean): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!active) return;
    const startedAt = Date.now();
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => {
      clearInterval(timer);
      setSeconds(0);
    };
  }, [active]);
  return active ? seconds : 0;
}
