import { API_URL } from "./api";
import type { AnalysisEvent } from "./types";

const KNOWN_TYPES = new Set([
  "progress",
  "listing_parsed",
  "market_verdict",
  "condition",
  "verdict",
  "error",
  "done",
]);

export interface StreamOptions {
  /** Forwarded as the Idempotency-Key header (matches the POST submission). */
  idempotencyKey?: string;
  signal?: AbortSignal;
}

/**
 * Parses a single SSE event block (the lines between blank-line separators)
 * into a typed AnalysisEvent, or null if it can't be parsed / isn't known.
 *
 * Exported for unit testing.
 */
export function parseSseBlock(block: string): AnalysisEvent | null {
  const dataLines: string[] = [];
  for (const rawLine of block.split("\n")) {
    const line = rawLine.replace(/\r$/, "");
    if (line.startsWith(":")) continue; // comment / heartbeat
    if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).replace(/^ /, ""));
    }
    // `event:` / `id:` fields are intentionally ignored; the payload `type`
    // field is the discriminant for our union.
  }

  if (dataLines.length === 0) return null;

  const payload = dataLines.join("\n").trim();
  if (!payload || payload === "[DONE]") return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(payload);
  } catch {
    return null;
  }

  if (
    parsed &&
    typeof parsed === "object" &&
    "type" in parsed &&
    typeof (parsed as { type: unknown }).type === "string" &&
    KNOWN_TYPES.has((parsed as { type: string }).type)
  ) {
    return parsed as AnalysisEvent;
  }
  return null;
}

/**
 * Opens the SSE stream for an analysis and invokes `onEvent` for each typed
 * event. Uses fetch + ReadableStream (NOT EventSource) so we can send the
 * Idempotency-Key header. Hits the FastAPI origin directly (NEXT_PUBLIC_API_URL)
 * to avoid the Next rewrite buffering the stream.
 *
 * Resolves when the stream ends (server closed, `done` event, or abort).
 */
export async function streamAnalysis(
  id: string,
  onEvent: (event: AnalysisEvent) => void,
  options: StreamOptions = {},
): Promise<void> {
  const url = `${API_URL}/api/analyses/${encodeURIComponent(id)}/events`;
  const headers: Record<string, string> = { Accept: "text/event-stream" };
  if (options.idempotencyKey) {
    headers["Idempotency-Key"] = options.idempotencyKey;
  }

  const res = await fetch(url, {
    method: "GET",
    headers,
    signal: options.signal,
    cache: "no-store",
  });

  if (!res.ok || !res.body) {
    throw new Error(`Failed to open event stream (HTTP ${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE events are separated by a blank line (\n\n).
      let sepIndex: number;
      while ((sepIndex = indexOfSeparator(buffer)) !== -1) {
        const block = buffer.slice(0, sepIndex.valueOf());
        buffer = buffer.slice(sepIndex + separatorLength(buffer, sepIndex));
        const event = parseSseBlock(block);
        if (event) onEvent(event);
      }
    }

    // Flush any trailing block without a terminating blank line.
    const tail = buffer.trim();
    if (tail) {
      const event = parseSseBlock(tail);
      if (event) onEvent(event);
    }
  } finally {
    reader.releaseLock();
  }
}

/** Index of the next event separator (\n\n or \r\n\r\n), or -1. */
function indexOfSeparator(buffer: string): number {
  const lf = buffer.indexOf("\n\n");
  const crlf = buffer.indexOf("\r\n\r\n");
  if (lf === -1) return crlf;
  if (crlf === -1) return lf;
  return Math.min(lf, crlf);
}

function separatorLength(buffer: string, index: number): number {
  return buffer.startsWith("\r\n\r\n", index) ? 4 : 2;
}
