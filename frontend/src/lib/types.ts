// TODO(M1): replace these hand-written DTOs with generated types from the backend
// OpenAPI schema via `npm run gen:api` -> src/types/api.d.ts, then re-export here.

/** Money amount in a given currency. */
export interface Money {
  amount: number;
  currency: string;
}

export type VerdictState = "below" | "fair" | "above" | "well_above" | "unknown";

export type Confidence = "high" | "medium" | "low" | "none";

export type ProgressStage = "extracting" | "comping" | "conditioning" | "synthesizing";

export interface ListingAttributes {
  brand?: string;
  model?: string;
  storage?: string;
  conditionGrade?: string;
}

export interface ListingDTO {
  title: string;
  category: string;
  attributes: ListingAttributes;
  price: Money;
  conditionClaim?: string | null;
  location?: { label: string } | null;
  images: string[];
}

export interface MarketVerdictDTO {
  state: VerdictState;
  asking: Money;
  percentile: number | null;
  typicalRange: { low: number; high: number; currency: string } | null;
  compCount: number;
}

export interface ConditionFlag {
  kind: string;
  detail: string;
  imageIndex?: number | null;
}

export interface ConditionMismatch {
  claim: string;
  evidence: string;
  imageIndex?: number | null;
}

export interface ConditionDTO {
  flags: ConditionFlag[];
  mismatches: ConditionMismatch[];
}

export interface VerdictDTO {
  state: VerdictState;
  headline: string;
  negotiationMessage: string;
  confidence: Confidence;
}

// ---- SSE events (discriminated union on `type`) ----

export interface ProgressEvent {
  type: "progress";
  stage: ProgressStage;
  message: string;
}

export interface ListingParsedEvent {
  type: "listing_parsed";
  listing: ListingDTO;
}

export interface MarketVerdictEvent {
  type: "market_verdict";
  marketVerdict: MarketVerdictDTO;
}

export interface ConditionEvent {
  type: "condition";
  condition: ConditionDTO;
}

export interface VerdictEvent {
  type: "verdict";
  verdict: VerdictDTO;
}

export interface ErrorEvent {
  type: "error";
  message: string;
}

export interface DoneEvent {
  type: "done";
}

export type AnalysisEvent =
  | ProgressEvent
  | ListingParsedEvent
  | MarketVerdictEvent
  | ConditionEvent
  | VerdictEvent
  | ErrorEvent
  | DoneEvent;

export type AnalysisEventType = AnalysisEvent["type"];

// ---- REST shapes ----

export interface CreateAnalysisRequest {
  url: string;
  options?: { forceFresh: boolean };
}

export interface CreateAnalysisResponse {
  analysisId: string;
  status: "queued";
}

/**
 * Snapshot returned by GET /api/analyses/{id} (resume path).
 * Fields are optional because an analysis may be partially complete.
 */
export interface AnalysisSnapshot {
  analysisId: string;
  status: "queued" | "running" | "done" | "error";
  listing?: ListingDTO | null;
  marketVerdict?: MarketVerdictDTO | null;
  condition?: ConditionDTO | null;
  verdict?: VerdictDTO | null;
  error?: string | null;
}
