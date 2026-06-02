import type {
  AnalysisSnapshot,
  CreateAnalysisRequest,
  CreateAnalysisResponse,
} from "./types";

/**
 * Origin of the FastAPI backend. Non-SSE calls go through the Next rewrite
 * (relative `/api/...`), but SSE must hit this origin directly — see sse.ts.
 */
export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface PostAnalysisOptions {
  forceFresh?: boolean;
  /** Optional Idempotency-Key header value to dedupe retried submissions. */
  idempotencyKey?: string;
  signal?: AbortSignal;
}

/**
 * Kicks off an analysis. Goes through the Next.js rewrite proxy (relative URL).
 * Returns 202 with the new analysis id.
 */
export async function postAnalysis(
  url: string,
  options: PostAnalysisOptions = {},
): Promise<CreateAnalysisResponse> {
  const body: CreateAnalysisRequest = { url };
  if (options.forceFresh) {
    body.options = { forceFresh: true };
  }

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (options.idempotencyKey) {
    headers["Idempotency-Key"] = options.idempotencyKey;
  }

  const res = await fetch("/api/analyses", {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal: options.signal,
  });

  if (!res.ok) {
    throw new Error(`Failed to start analysis (HTTP ${res.status})`);
  }

  return (await res.json()) as CreateAnalysisResponse;
}

/** Fetches a snapshot of an analysis (resume path). */
export async function getSnapshot(
  id: string,
  signal?: AbortSignal,
): Promise<AnalysisSnapshot> {
  const res = await fetch(`/api/analyses/${encodeURIComponent(id)}`, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal,
  });

  if (!res.ok) {
    throw new Error(`Failed to fetch analysis (HTTP ${res.status})`);
  }

  return (await res.json()) as AnalysisSnapshot;
}

/** Generates a reasonably-unique idempotency key for a submission. */
export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
