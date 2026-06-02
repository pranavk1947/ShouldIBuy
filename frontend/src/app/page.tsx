"use client";

import { useState } from "react";
import AnalyzePanel from "@/components/AnalyzePanel";
import { EXAMPLES } from "@/lib/examples";

export default function Home() {
  const [inputUrl, setInputUrl] = useState("");
  // The URL that has actually been submitted for analysis.
  const [submittedUrl, setSubmittedUrl] = useState<string | null>(null);
  // Bump on every submit so AnalyzePanel remounts and restarts cleanly.
  const [runKey, setRunKey] = useState(0);

  function submit(url: string) {
    const trimmed = url.trim();
    if (!trimmed) return;
    setInputUrl(trimmed);
    setSubmittedUrl(trimmed);
    setRunKey((k) => k + 1);
  }

  return (
    <main>
      <section className="hero">
        <h1>Should I buy this?</h1>
        <p className="subtitle">
          Paste a used-item listing URL. We&apos;ll check if the price is fair and draft a
          negotiation message.
        </p>

        <form
          className="url-form"
          onSubmit={(e) => {
            e.preventDefault();
            submit(inputUrl);
          }}
        >
          <input
            className="url-input"
            type="url"
            inputMode="url"
            placeholder="https://…/some-listing"
            value={inputUrl}
            onChange={(e) => setInputUrl(e.target.value)}
            aria-label="Listing URL"
          />
          <button className="btn" type="submit" disabled={!inputUrl.trim()}>
            Check
          </button>
        </form>

        <div className="examples">
          <div className="label">Try an example</div>
          <div className="chips">
            {EXAMPLES.map((ex) => (
              <button
                key={ex.url}
                type="button"
                className="chip"
                onClick={() => submit(ex.url)}
              >
                {ex.label}
              </button>
            ))}
          </div>
        </div>
      </section>

      {submittedUrl && <AnalyzePanel key={runKey} url={submittedUrl} />}
    </main>
  );
}
