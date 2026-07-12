"use client";

import { useState, type FormEvent } from "react";
import { FileUp, X } from "lucide-react";

interface WorkbookDialogProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (name: string, timezone: string, file: File) => Promise<void>;
}

export function WorkbookDialog({ open, onClose, onSubmit }: WorkbookDialogProps) {
  const [name, setName] = useState("My Planner");
  const [timezone, setTimezone] = useState("Asia/Kolkata");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  if (!open) return null;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    try {
      await onSubmit(name, timezone, file);
      onClose();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="dialog-backdrop" role="presentation">
      <section className="dialog" role="dialog" aria-modal="true" aria-labelledby="workspace-dialog-title">
        <header><div><p className="eyebrow">Workbook</p><h2 id="workspace-dialog-title">Create workspace</h2></div><button className="icon-button" onClick={onClose} title="Close" type="button"><X size={18} /></button></header>
        <form onSubmit={submit} className="stack-form">
          <label>Name<input value={name} onChange={(event) => setName(event.target.value)} required /></label>
          <label>Timezone<input value={timezone} onChange={(event) => setTimezone(event.target.value)} required /></label>
          <label className="file-field"><FileUp size={18} aria-hidden="true" /><span>{file?.name ?? "Choose Planner OS workbook"}</span><input type="file" accept=".xlsx" onChange={(event) => setFile(event.target.files?.[0] ?? null)} required /></label>
          <button className="primary-button" disabled={busy || !file} type="submit">{busy ? "Uploading..." : "Create workspace"}</button>
        </form>
      </section>
    </div>
  );
}
