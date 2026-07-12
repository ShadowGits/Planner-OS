"use client";

import { CheckCircle2, CircleAlert, ClipboardCheck } from "lucide-react";
import type { Envelope } from "@/lib/types";

interface ResultPanelProps { result: Envelope | null; }

export function ResultPanel({ result }: ResultPanelProps) {
  return (
    <section className="result-panel" aria-live="polite" aria-labelledby="result-title">
      <header><div className="section-icon"><ClipboardCheck size={19} /></div><div><h2 id="result-title">Latest result</h2></div></header>
      {!result ? <div className="empty-result">No result yet.</div> : (
        <div className="result-body">
          <div className={result.success ? "result-status success" : "result-status error"}>
            {result.success ? <CheckCircle2 size={18} /> : <CircleAlert size={18} />}<strong>{result.message}</strong>
          </div>
          {result.preview_id && <p><span className="label">Preview</span><code>{result.preview_id}</code></p>}
          <pre>{JSON.stringify(result.data, null, 2)}</pre>
        </div>
      )}
    </section>
  );
}
