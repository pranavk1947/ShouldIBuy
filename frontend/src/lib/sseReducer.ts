import type {
  AnalysisEvent,
  ConditionDTO,
  ListingDTO,
  MarketVerdictDTO,
  ProgressStage,
  VerdictDTO,
} from "./types";

export type Phase = "idle" | "running" | "done" | "error";

/**
 * Pure, serializable UI state assembled from the SSE event stream.
 * This is the one piece of real logic in M0, so it is kept pure and tested.
 */
export interface AnalysisState {
  phase: Phase;
  stage: ProgressStage | null;
  progressMessage: string | null;
  listing: ListingDTO | null;
  marketVerdict: MarketVerdictDTO | null;
  condition: ConditionDTO | null;
  verdict: VerdictDTO | null;
  error: string | null;
}

export const initialState: AnalysisState = {
  phase: "idle",
  stage: null,
  progressMessage: null,
  listing: null,
  marketVerdict: null,
  condition: null,
  verdict: null,
  error: null,
};

/** Stage order, used so a late/out-of-order progress event can't go backwards. */
const STAGE_ORDER: Record<ProgressStage, number> = {
  extracting: 0,
  comping: 1,
  conditioning: 2,
  synthesizing: 3,
};

/** Pure reducer: (state, event) -> next state. No side effects. */
export function sseReducer(state: AnalysisState, event: AnalysisEvent): AnalysisState {
  switch (event.type) {
    case "progress": {
      // Don't regress to an earlier stage if events arrive out of order.
      const prevRank = state.stage ? STAGE_ORDER[state.stage] : -1;
      const nextRank = STAGE_ORDER[event.stage];
      const stage = nextRank >= prevRank ? event.stage : state.stage;
      return {
        ...state,
        phase: state.phase === "idle" ? "running" : state.phase,
        stage,
        progressMessage: event.message,
      };
    }

    case "listing_parsed":
      return {
        ...state,
        phase: state.phase === "idle" ? "running" : state.phase,
        listing: event.listing,
      };

    case "market_verdict":
      return {
        ...state,
        phase: state.phase === "idle" ? "running" : state.phase,
        marketVerdict: event.marketVerdict,
      };

    case "condition":
      return {
        ...state,
        phase: state.phase === "idle" ? "running" : state.phase,
        condition: event.condition,
      };

    case "verdict":
      return {
        ...state,
        phase: state.phase === "idle" ? "running" : state.phase,
        verdict: event.verdict,
      };

    case "error":
      return {
        ...state,
        phase: "error",
        error: event.message,
      };

    case "done":
      // `done` after an error stays errored.
      return {
        ...state,
        phase: state.phase === "error" ? "error" : "done",
        progressMessage: null,
      };

    default: {
      // Exhaustiveness guard: unknown events are ignored.
      const _exhaustive: never = event;
      void _exhaustive;
      return state;
    }
  }
}

/** Convenience: fold an array of events from the initial state. */
export function reduceEvents(events: AnalysisEvent[]): AnalysisState {
  return events.reduce(sseReducer, initialState);
}
