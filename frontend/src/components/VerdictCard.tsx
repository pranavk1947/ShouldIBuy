"use client";

import { useState } from "react";
import type { AnalysisState } from "@/lib/sseReducer";
import type { ListingDTO, MarketVerdictDTO, ProgressStage } from "@/lib/types";

interface Props {
  state: AnalysisState;
  sourceUrl: string;
}

const STAGE_PROGRESS: Record<ProgressStage, number> = {
  extracting: 25,
  comping: 50,
  conditioning: 75,
  synthesizing: 90,
};

function money(amount: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(amount);
  } catch {
    return `${currency} ${amount}`;
  }
}

export default function VerdictCard({ state, sourceUrl }: Props) {
  const { phase, stage, progressMessage, listing, marketVerdict, condition, verdict, error } =
    state;

  const progressPct =
    phase === "done"
      ? 100
      : stage
        ? STAGE_PROGRESS[stage]
        : phase === "running"
          ? 8
          : 0;

  return (
    <div className="card" aria-live="polite">
      {/* Progress line */}
      {phase !== "error" && (
        <div className="progress-track" role="progressbar" aria-valuenow={progressPct}>
          <div className="progress-bar" style={{ width: `${progressPct}%` }} />
        </div>
      )}

      {error && <div className="error-banner">⚠️ {error}</div>}

      {!error && progressMessage && phase !== "done" && (
        <div className="progress-message">{progressMessage}</div>
      )}

      {/* Verdict banner (final synthesis) */}
      {verdict && (
        <div className="verdict-banner" data-state={verdict.state}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: 8,
            }}
          >
            <span className="verdict-headline">{verdict.headline}</span>
            <span className="badge" data-confidence={verdict.confidence}>
              {verdict.confidence === "none"
                ? "low confidence"
                : `${verdict.confidence} confidence`}
            </span>
          </div>
          {verdict.negotiationMessage ? (
            <NegotiationBlock message={verdict.negotiationMessage} />
          ) : null}
        </div>
      )}

      {/* Listing section */}
      <div className="card-section">
        <p className="section-title">Listing</p>
        {listing ? <ListingBlock listing={listing} /> : <ListingSkeleton />}
      </div>

      {/* Market verdict section */}
      <div className="card-section">
        <p className="section-title">Market</p>
        {marketVerdict ? (
          <MarketBlock market={marketVerdict} />
        ) : phase === "done" ? (
          <p className="note">No market data was produced.</p>
        ) : (
          <div className="skeleton skeleton-line" style={{ width: "60%" }} />
        )}
      </div>

      {/* Condition section */}
      <div className="card-section">
        <p className="section-title">Condition</p>
        {condition ? (
          <ConditionBlock
            flags={condition.flags}
            mismatches={condition.mismatches}
          />
        ) : phase === "done" ? (
          <p className="note">No condition issues detected.</p>
        ) : (
          <div className="skeleton skeleton-line" style={{ width: "45%" }} />
        )}
      </div>

      {/* Graceful unknown / no-verdict end state */}
      {phase === "done" && !verdict && (
        <div className="card-section">
          <p className="note">
            We couldn&apos;t reach a confident verdict — not enough comparable listings. The
            parsed listing and any condition flags are shown above.
          </p>
        </div>
      )}

      <div className="card-section">
        <a
          className="listing-meta"
          href={sourceUrl}
          target="_blank"
          rel="noopener noreferrer"
        >
          View original listing ↗
        </a>
      </div>
    </div>
  );
}

function ListingBlock({ listing }: { listing: ListingDTO }) {
  const { attributes } = listing;
  const metaParts = [
    attributes.brand,
    attributes.model,
    attributes.storage,
    attributes.conditionGrade,
    listing.conditionClaim ?? undefined,
    listing.location?.label,
  ].filter(Boolean);

  return (
    <div className="listing">
      {listing.images[0] ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          className="listing-thumb"
          src={listing.images[0]}
          alt={listing.title}
        />
      ) : (
        <div className="listing-thumb" aria-hidden="true" />
      )}
      <div>
        <p className="listing-title">{listing.title}</p>
        {metaParts.length > 0 && <p className="listing-meta">{metaParts.join(" · ")}</p>}
        <p className="listing-price">{money(listing.price.amount, listing.price.currency)}</p>
      </div>
    </div>
  );
}

function ListingSkeleton() {
  return (
    <div className="listing">
      <div className="skeleton skeleton-block" />
      <div style={{ flex: 1 }}>
        <div className="skeleton skeleton-line" style={{ width: "70%" }} />
        <div className="skeleton skeleton-line" style={{ width: "40%" }} />
        <div className="skeleton skeleton-line" style={{ width: "25%" }} />
      </div>
    </div>
  );
}

function MarketBlock({ market }: { market: MarketVerdictDTO }) {
  if (market.state === "unknown" || !market.typicalRange || market.compCount === 0) {
    return (
      <p className="note">
        Not enough comparable listings to price this confidently
        {market.compCount > 0 ? ` (only ${market.compCount} found).` : "."}
      </p>
    );
  }

  const { low, high, currency } = market.typicalRange;
  const asking = market.asking.amount;
  // Position the asking-price marker within [low, high], clamped + padded.
  const span = Math.max(high - low, 1);
  const rawPct = ((asking - low) / span) * 100;
  const markerPct = Math.min(98, Math.max(2, rawPct));

  return (
    <div>
      <p className="listing-meta">
        Asking <strong>{money(asking, market.asking.currency)}</strong>
        {market.percentile != null ? ` · ${market.percentile}th percentile` : ""} · {market.compCount}{" "}
        comparable listings
      </p>
      <div className="market-bar-wrap">
        <div className="market-bar">
          <div
            className="market-marker"
            style={{ left: `${markerPct}%` }}
            title={money(asking, market.asking.currency)}
          />
        </div>
        <div className="market-legend">
          <span>{money(low, currency)}</span>
          <span>typical range</span>
          <span>{money(high, currency)}</span>
        </div>
      </div>
    </div>
  );
}

function ConditionBlock({
  flags,
  mismatches,
}: {
  flags: MarketBlockFlags["flags"];
  mismatches: MarketBlockFlags["mismatches"];
}) {
  if (flags.length === 0 && mismatches.length === 0) {
    return <p className="note">No condition issues detected.</p>;
  }
  return (
    <ul className="flag-list">
      {flags.map((f, i) => (
        <li className="flag" key={`flag-${i}`}>
          <span className="flag-kind">{f.kind}:</span>
          <span>{f.detail}</span>
        </li>
      ))}
      {mismatches.map((m, i) => (
        <li className="flag mismatch" key={`mismatch-${i}`}>
          <span className="flag-kind">claim mismatch:</span>
          <span>
            says &ldquo;{m.claim}&rdquo; — {m.evidence}
          </span>
        </li>
      ))}
    </ul>
  );
}

// Local helper type to keep ConditionBlock props tidy.
type MarketBlockFlags = {
  flags: { kind: string; detail: string; imageIndex?: number | null }[];
  mismatches: { claim: string; evidence: string; imageIndex?: number | null }[];
};

function NegotiationBlock({ message }: { message: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(message);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard may be unavailable (insecure context); fail silently.
    }
  }

  return (
    <div>
      <div className="negotiation">{message}</div>
      <div className="copy-row">
        <button type="button" className="btn btn-ghost" onClick={copy}>
          Copy negotiation message
        </button>
        {copied && <span className="copy-status">Copied!</span>}
      </div>
    </div>
  );
}
