import { describe, expect, it } from "vitest";
import type { AnalysisEvent } from "./types";
import { initialState, reduceEvents, sseReducer } from "./sseReducer";

// A recorded "happy path" event sequence (below-market verdict).
const HAPPY_PATH: AnalysisEvent[] = [
  { type: "progress", stage: "extracting", message: "Reading the listing…" },
  {
    type: "listing_parsed",
    listing: {
      title: "iPhone 13 Pro 128GB",
      category: "phones",
      attributes: { brand: "Apple", model: "iPhone 13 Pro", storage: "128GB" },
      price: { amount: 420, currency: "USD" },
      conditionClaim: "Good",
      location: { label: "Brooklyn, NY" },
      images: ["https://img/1.jpg", "https://img/2.jpg"],
    },
  },
  { type: "progress", stage: "comping", message: "Comparing prices…" },
  {
    type: "market_verdict",
    marketVerdict: {
      state: "below",
      asking: { amount: 420, currency: "USD" },
      percentile: 18,
      typicalRange: { low: 460, high: 560, currency: "USD" },
      compCount: 37,
    },
  },
  { type: "progress", stage: "conditioning", message: "Checking condition…" },
  {
    type: "condition",
    condition: {
      flags: [{ kind: "scratch", detail: "Hairline scratch on screen", imageIndex: 1 }],
      mismatches: [],
    },
  },
  { type: "progress", stage: "synthesizing", message: "Writing verdict…" },
  {
    type: "verdict",
    verdict: {
      state: "below",
      headline: "Below market — good buy",
      negotiationMessage: "Would you take $400?",
      confidence: "high",
    },
  },
  { type: "done" },
];

describe("sseReducer", () => {
  it("starts from a clean idle state", () => {
    expect(initialState.phase).toBe("idle");
    expect(initialState.listing).toBeNull();
    expect(initialState.verdict).toBeNull();
  });

  it("folds the happy-path sequence into a complete, done state", () => {
    const state = reduceEvents(HAPPY_PATH);

    expect(state.phase).toBe("done");
    expect(state.listing?.title).toBe("iPhone 13 Pro 128GB");
    expect(state.marketVerdict?.state).toBe("below");
    expect(state.marketVerdict?.compCount).toBe(37);
    expect(state.condition?.flags).toHaveLength(1);
    expect(state.verdict?.confidence).toBe("high");
    expect(state.verdict?.negotiationMessage).toBe("Would you take $400?");
    // progressMessage cleared on done
    expect(state.progressMessage).toBeNull();
    expect(state.error).toBeNull();
  });

  it("transitions idle -> running on the first event", () => {
    const next = sseReducer(initialState, HAPPY_PATH[0]);
    expect(next.phase).toBe("running");
    expect(next.stage).toBe("extracting");
  });

  it("does not regress to an earlier stage on out-of-order progress", () => {
    const advanced = sseReducer(
      { ...initialState, phase: "running", stage: "synthesizing" },
      { type: "progress", stage: "extracting", message: "late event" },
    );
    expect(advanced.stage).toBe("synthesizing");
    // but message still updates
    expect(advanced.progressMessage).toBe("late event");
  });

  it("handles the unknown / not-enough-comps path gracefully", () => {
    const events: AnalysisEvent[] = [
      {
        type: "listing_parsed",
        listing: {
          title: "Obscure widget",
          category: "misc",
          attributes: {},
          price: { amount: 99, currency: "USD" },
          images: [],
        },
      },
      {
        type: "market_verdict",
        marketVerdict: {
          state: "unknown",
          asking: { amount: 99, currency: "USD" },
          percentile: null,
          typicalRange: null,
          compCount: 0,
        },
      },
      {
        type: "verdict",
        verdict: {
          state: "unknown",
          headline: "Not enough comparable listings",
          negotiationMessage: "",
          confidence: "none",
        },
      },
      { type: "done" },
    ];

    const state = reduceEvents(events);
    expect(state.phase).toBe("done");
    expect(state.marketVerdict?.state).toBe("unknown");
    expect(state.marketVerdict?.compCount).toBe(0);
    expect(state.verdict?.confidence).toBe("none");
    expect(state.listing?.title).toBe("Obscure widget");
  });

  it("captures errors and stays errored even after done", () => {
    let state = sseReducer(initialState, { type: "progress", stage: "extracting", message: "x" });
    state = sseReducer(state, { type: "error", message: "Listing not found" });
    expect(state.phase).toBe("error");
    expect(state.error).toBe("Listing not found");

    state = sseReducer(state, { type: "done" });
    expect(state.phase).toBe("error");
  });
});
