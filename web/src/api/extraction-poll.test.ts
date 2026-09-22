// The queued extraction path: GET /extractions/{id} every 2 s until done or error, with a cancel.
// `pollExtraction` takes its clock, its sleep and its cancel flag, so this runs with no timers and
// no network.

import { describe, expect, it, vi } from "vitest";
import {
  EXTRACTION_POLL_MS,
  ExtractionCancelled,
  pollExtraction,
  type PollDeps,
} from "@/api/hooks";
import type { ExtractionStatus } from "@/api/types";

function state(status: ExtractionStatus["status"], extra: Partial<ExtractionStatus> = {}): ExtractionStatus {
  return { id: "e1", meeting_id: "m1", status, points: [], ...extra };
}

function harness(answers: ExtractionStatus[], overrides: Partial<PollDeps> = {}) {
  const waits: number[] = [];
  const paths: string[] = [];
  let clock = 0;
  const deps: PollDeps = {
    get: async (path) => {
      paths.push(path);
      return answers.shift() ?? state("done");
    },
    wait: async (ms) => {
      waits.push(ms);
      clock += ms;
    },
    now: () => clock,
    cancelled: () => false,
    ...overrides,
  };
  return { deps, waits, paths };
}

describe("pollExtraction", () => {
  it("polls every 2 s until the job is done, then returns its points", async () => {
    const points = [{ id: "p1", kind: "action", text: "Send the deck" }] as unknown as ExtractionStatus["points"];
    const { deps, waits, paths } = harness([
      state("queued"),
      state("running"),
      state("done", { points, created_points: 1 }),
    ]);
    const result = await pollExtraction("e1", deps);
    expect(result.status).toBe("done");
    expect(result.points).toEqual(points);
    expect(paths).toEqual(["/extractions/e1", "/extractions/e1", "/extractions/e1"]);
    expect(waits).toEqual([EXTRACTION_POLL_MS, EXTRACTION_POLL_MS, EXTRACTION_POLL_MS]);
  });

  it("reports the phase as the job moves from queued to running", async () => {
    const onPhase = vi.fn();
    const { deps } = harness([state("queued"), state("running"), state("done")], { onPhase });
    await pollExtraction("e1", deps);
    expect(onPhase.mock.calls.map((c) => c[0])).toEqual(["queued", "running"]);
  });

  it("throws the job's own error rather than polling for ever", async () => {
    const { deps, paths } = harness([state("error", { error: "Vertex AI refused the call: 429 quota" })]);
    await expect(pollExtraction("e1", deps)).rejects.toThrow("429 quota");
    expect(paths).toHaveLength(1);
  });

  it("stops at once when the caller cancels, and says the job may still land", async () => {
    let stop = false;
    const { deps, paths } = harness([state("queued"), state("queued"), state("done")], {
      cancelled: () => stop,
    });
    const polling = pollExtraction("e1", {
      ...deps,
      wait: async (ms) => {
        await deps.wait(ms);
        stop = true; // cancelled while waiting for the next tick
      },
    });
    await expect(polling).rejects.toBeInstanceOf(ExtractionCancelled);
    expect(paths).toHaveLength(0);
  });

  it("never polls at all if it was cancelled before the first tick", async () => {
    const { deps, paths, waits } = harness([state("done")], { cancelled: () => true });
    await expect(pollExtraction("e1", deps)).rejects.toBeInstanceOf(ExtractionCancelled);
    expect(paths).toHaveLength(0);
    expect(waits).toHaveLength(0);
  });

  it("gives up after the timeout instead of hanging on a stuck job", async () => {
    const answers = Array.from({ length: 400 }, () => state("running"));
    const { deps } = harness(answers, { timeoutMs: 10_000 });
    await expect(pollExtraction("e1", deps)).rejects.toThrow("still running after 10 minutes");
  });
});
