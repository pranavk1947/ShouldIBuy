"use client";

import { useEffect, useReducer, useRef } from "react";
import { newIdempotencyKey, postAnalysis } from "@/lib/api";
import { streamAnalysis } from "@/lib/sse";
import { initialState, sseReducer } from "@/lib/sseReducer";
import VerdictCard from "./VerdictCard";

interface Props {
  url: string;
}

/**
 * Client component that drives a single analysis run:
 *  1. POST /api/analyses (with an Idempotency-Key)
 *  2. open the SSE stream against the FastAPI origin directly
 *  3. fold events into reducer state, rendered by VerdictCard.
 *
 * Mounted fresh (via key) per submission by the parent page.
 */
export default function AnalyzePanel({ url }: Props) {
  const [state, dispatch] = useReducer(sseReducer, initialState);
  const startedRef = useRef(false);

  useEffect(() => {
    // Guard against React 18 StrictMode double-invoke in dev.
    if (startedRef.current) return;
    startedRef.current = true;

    const controller = new AbortController();
    const idempotencyKey = newIdempotencyKey();

    (async () => {
      try {
        const { analysisId } = await postAnalysis(url, {
          idempotencyKey,
          signal: controller.signal,
        });

        await streamAnalysis(analysisId, (event) => dispatch(event), {
          idempotencyKey,
          signal: controller.signal,
        });
      } catch (err) {
        if (controller.signal.aborted) return;
        dispatch({
          type: "error",
          message: err instanceof Error ? err.message : "Something went wrong.",
        });
      }
    })();

    return () => controller.abort();
  }, [url]);

  return <VerdictCard state={state} sourceUrl={url} />;
}
