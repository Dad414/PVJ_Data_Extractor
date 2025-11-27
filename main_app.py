#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PVJ Extractor — GUI Frontend
Part 1/6 of ~3000-line app
Author: Zeeshan Ali

This module provides a Tkinter desktop UI that:
- Lets you add one or more PVJ PDFs (e.g., 2025_08_v19_n7.pdf)
- Runs the OCR+parse pipeline in a background thread
- Writes Excel(s) named exactly like the PDF(s): <base>.xlsx
- Shows progress, logs, and errors
"""

from __future__ import annotations
import os
import sys
import time
import queue
import threading
import traceback
from dataclasses import dataclass, field
from typing import List, Optional, Callable, Dict

# --- Tkinter UI ---
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# --- Soft imports (the rest of the app will be added in later parts) ---
# We import lazily inside the worker to allow this GUI to open even if modules are missing.


# ---------------------------
# App-wide constants & helpers
# ---------------------------

APP_TITLE = "PVJ OCR Extractor"
APP_VERSION = "v1.0 (GUI)"
DEFAULT_OUTPUT_DIR = os.path.expanduser("~/PVJ_Outputs")

SUPPORTED_PDF_EXTS = {".pdf", ".PDF"}


def ensure_dir(path: str) -> None:
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def pdf_to_xlsx_name(pdf_path: str, out_dir: Optional[str] = None) -> str:
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    out_dir = out_dir or os.path.dirname(pdf_path)
    ensure_dir(out_dir)
    return os.path.join(out_dir, f"{base}.xlsx")


def human_time(secs: float) -> str:
    if secs < 60:
        return f"{secs:.1f}s"
    m, s = divmod(int(secs), 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"


@dataclass
class JobResult:
    pdf_path: str
    xlsx_path: Optional[str]
    ok: bool
    error: Optional[str] = None
    duration_sec: float = 0.0
    parsed_rows: int = 0


@dataclass
class AppState:
    files: List[str] = field(default_factory=list)
    output_dir: str = field(default=DEFAULT_OUTPUT_DIR)
    running: bool = False
    cancel_requested: bool = False
    total_jobs: int = 0
    completed_jobs: int = 0


# ---------------------------
# Worker (threaded pipeline)
# ---------------------------

class PipelineWorker(threading.Thread):
    """
    Background worker that processes a list of PDFs and writes Excels.
    Communicates via thread-safe queues:
      - log_q: text log lines
      - prog_q: progress updates (0..1 floats and status dict)
      - res_q: per-file JobResult objects
    """
    def __init__(
        self,
        files: List[str],
        output_dir: str,
        log_q: queue.Queue,
        prog_q: queue.Queue,
        res_q: queue.Queue,
        cancel_flag: Callable[[], bool],
    ):
        super().__init__(daemon=True)
        self.files = files
        self.output_dir = output_dir
        self.log_q = log_q
        self.prog_q = prog_q
        self.res_q = res_q
        self.cancel_flag = cancel_flag

    def log(self, msg: str) -> None:
        self.log_q.put(msg)

    def send_progress(self, frac: float, detail: Optional[Dict] = None) -> None:
        self.prog_q.put({"fraction": max(0.0, min(1.0, frac)), "detail": detail or {}})

    def run(self) -> None:
        t0_batch = time.time()
        n = len(self.files)
        for idx, pdf_path in enumerate(self.files, start=1):
            if self.cancel_flag():
                self.log("⛔️ Cancel detected — stopping remaining jobs.")
                break

            t0 = time.time()
            self.log(f"\n▶️  [{idx}/{n}] Processing: {pdf_path}")
            excel_path = pdf_to_xlsx_name(pdf_path, self.output_dir)
            rows_written = 0
            ok = True
            err_text = None

            try:
                # Lazy imports to allow GUI to start without other modules
                try:
                    import config as app_config
                except Exception:
                    app_config = None

                try:
                    import extractor
                except Exception:
                    extractor = None

                try:
                    import excel_writer
                except Exception:
                    excel_writer = None

                # Send initial progress
                self.send_progress((idx - 1) / n, {"file": os.path.basename(pdf_path), "stage": "start"})

                # 1) If extractor module exists, use it. Otherwise, fallback to minimal stub.
                if extractor is not None and hasattr(extractor, "extract_to_dataframe"):
                    # extractor.extract_to_dataframe must accept (pdf_path, config, progress_callback, cancel_flag)
                    self.log("   • Running pipeline (OCR + parse)…")
                    cfg = getattr(app_config, "DEFAULTS", {}) if app_config else {}
                    df, summaries = extractor.extract_to_dataframe(
                        pdf_path=pdf_path,
                        config=cfg,
                        progress_cb=lambda f, s: self.send_progress(((idx - 1) + f) / n, {"file": os.path.basename(pdf_path), **s}),
                        cancel_cb=self.cancel_flag,
                    )
                    rows_written = int(getattr(df, "shape", (0, 0))[0])

                    # 2) Write Excel
                    if excel_writer is not None and hasattr(excel_writer, "write_full_workbook"):
                        self.log(f"   • Writing Excel → {excel_path}")
                        excel_writer.write_full_workbook(
                            df=df,
                            summaries=summaries,
                            out_path=excel_path,
                            config=cfg,
                        )
                    else:
                        # Safe fallback: pandas only
                        self.log("   • excel_writer not found — writing single 'Data' sheet via pandas.")
                        ensure_dir(os.path.dirname(excel_path))
                        with pd.ExcelWriter(excel_path, engine="openpyxl") as w:
                            df.to_excel(w, sheet_name="Data", index=False)

                else:
                    # Fallback stub if extractor not yet provided
                    self.log("   • extractor module not found — creating empty workbook with headers.")
                    import pandas as pd
                    cols = [
                        "Reg_No", "Variety_Name", "Crop", "Variety_Type",
                        "Applicant", "Applicant_Type", "Charter_of_Crop",
                        "Taxonomy", "Productivity", "Distinctiveness",
                        "Developer_or_Breeder", "Page_Number"
                    ]
                    df = pd.DataFrame(columns=cols)
                    ensure_dir(os.path.dirname(excel_path))
                    with pd.ExcelWriter(excel_path, engine="openpyxl") as w:
                        df.to_excel(w, sheet_name="Data", index=False)

                self.send_progress(idx / n, {"file": os.path.basename(pdf_path), "stage": "done"})

            except Exception as e:
                ok = False
                err_text = "".join(traceback.format_exception(e))
                self.log(f"❌ Error: {e}\n{err_text}")

            dt = time.time() - t0
            self.res_q.put(
                JobResult(
                    pdf_path=pdf_path,
                    xlsx_path=excel_path if ok else None,
                    ok=ok,
                    error=err_text,
                    duration_sec=dt,
                    parsed_rows=rows_written,
                )
            )
        self.log(f"\n✅ Batch finished in {human_time(time.time() - t0_batch)}.")


# ---------------------------
# Tkinter GUI
# ---------------------------

class PVJApp(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master)
        self.master = master
        self.state = AppState()
        self.log_q: queue.Queue = queue.Queue()
        self.prog_q: queue.Queue = queue.Queue()
        self.res_q: queue.Queue = queue.Queue()
        self.worker: Optional[PipelineWorker] = None

        self._build_ui()
        self._poll_queues()

    # --- UI Construction ---
    def _build_ui(self) -> None:
        self.master.title(f"{APP_TITLE} — {APP_VERSION}")
        self.master.geometry("980x680")
        self.master.minsize(900, 620)

        # Top bar
        top = ttk.Frame(self.master, padding=(12, 10, 12, 6))
        top.pack(fill="x")

        ttk.Label(top, text="Selected PDFs:", font=("Segoe UI", 10, "bold")).pack(side="left")

        # Buttons: add, remove, clear
        btns = ttk.Frame(top)
        btns.pack(side="right")
        ttk.Button(btns, text="Add PDF(s)…", command=self.on_add_files).pack(side="left", padx=4)
        ttk.Button(btns, text="Remove", command=self.on_remove_selected).pack(side="left", padx=4)
        ttk.Button(btns, text="Clear", command=self.on_clear).pack(side="left", padx=4)

        # File listbox
        mid = ttk.Frame(self.master, padding=(12, 0, 12, 6))
        mid.pack(fill="both", expand=True)

        self.lb = tk.Listbox(mid, selectmode=tk.EXTENDED, height=10, activestyle="none")
        self.lb_scroll = ttk.Scrollbar(mid, orient="vertical", command=self.lb.yview)
        self.lb.config(yscrollcommand=self.lb_scroll.set)
        self.lb.pack(side="left", fill="both", expand=True, padx=(0, 6), pady=(4, 6))
        self.lb_scroll.pack(side="left", fill="y", pady=(4, 6))

        # Output folder chooser
        out = ttk.Frame(self.master, padding=(12, 0, 12, 6))
        out.pack(fill="x")
        ttk.Label(out, text="Output folder:", font=("Segoe UI", 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar(value=self.state.output_dir)
        self.out_entry = ttk.Entry(out, textvariable=self.out_var)
        self.out_entry.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(out, text="Browse…", command=self.on_choose_outdir).pack(side="left")

        # Progress area
        prog = ttk.LabelFrame(self.master, text="Progress", padding=(12, 8, 12, 8))
        prog.pack(fill="x", padx=12, pady=(6, 6))

        self.pb = ttk.Progressbar(prog, orient="horizontal", mode="determinate")
        self.pb.pack(fill="x", padx=2, pady=(4, 6))

        self.status_var = tk.StringVar(value="Idle")
        self.eta_var = tk.StringVar(value="")
        stat_line = ttk.Frame(prog)
        stat_line.pack(fill="x")
        ttk.Label(stat_line, textvariable=self.status_var).pack(side="left")
        ttk.Label(stat_line, textvariable=self.eta_var, foreground="#666").pack(side="right")

        # Start/Cancel buttons
        controls = ttk.Frame(self.master, padding=(12, 0, 12, 6))
        controls.pack(fill="x")
        self.btn_start = ttk.Button(controls, text="Run Extraction", command=self.on_start)
        self.btn_start.pack(side="left")
        self.btn_cancel = ttk.Button(controls, text="Cancel", command=self.on_cancel, state=tk.DISABLED)
        self.btn_cancel.pack(side="left", padx=6)

        # Log panel
        logf = ttk.LabelFrame(self.master, text="Logs", padding=(12, 8, 12, 8))
        logf.pack(fill="both", expand=True, padx=12, pady=(6, 12))

        self.log_txt = tk.Text(logf, wrap="word", height=12)
        self.log_txt_scroll = ttk.Scrollbar(logf, orient="vertical", command=self.log_txt.yview)
        self.log_txt.config(yscrollcommand=self.log_txt_scroll.set)
        self.log_txt.pack(side="left", fill="both", expand=True)
        self.log_txt_scroll.pack(side="left", fill="y")

        # Footer
        footer = ttk.Frame(self.master, padding=(12, 0, 12, 12))
        footer.pack(fill="x")
        ttk.Label(footer, text="Tip: Output Excel name matches the PDF name (e.g., 2025_08_v19_n7.xlsx).").pack(side="left")

    # --- Queue polling ---
    def _poll_queues(self) -> None:
        # Logs
        try:
            while True:
                line = self.log_q.get_nowait()
                self._append_log(line)
        except queue.Empty:
            pass

        # Progress updates
        try:
            while True:
                item = self.prog_q.get_nowait()
                frac = float(item.get("fraction", 0.0))
                detail = item.get("detail", {}) or {}
                self.pb["value"] = int(frac * 100)
                file = detail.get("file")
                stage = detail.get("stage")
                if file and stage:
                    self.status_var.set(f"{stage.title()} — {file} ({int(frac*100)}%)")
                elif file:
                    self.status_var.set(f"{file} — {int(frac*100)}%")
                else:
                    self.status_var.set(f"{int(frac*100)}%")
        except queue.Empty:
            pass

        # Results
        try:
            while True:
                res: JobResult = self.res_q.get_nowait()
                self.state.completed_jobs += 1
                if res.ok:
                    self._append_log(f"✅ Done: {os.path.basename(res.pdf_path)} → {res.xlsx_path} "
                                     f"({res.parsed_rows} rows, {human_time(res.duration_sec)})")
                else:
                    self._append_log(f"❌ Failed: {os.path.basename(res.pdf_path)}")
                    if res.error:
                        self._append_log(res.error)

                # ETA line
                done = self.state.completed_jobs
                total = self.state.total_jobs
                if done > 0:
                    # rough ETA can be computed by average duration; but we keep it simple
                    self.eta_var.set(f"Completed {done}/{total}")
                if done == total:
                    self._on_batch_finished()
        except queue.Empty:
            pass

        # keep polling
        self.master.after(100, self._poll_queues)

    # --- UI callbacks ---
    def on_add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select PVJ PDF(s)",
            filetypes=[("PDF files", "*.pdf")],
        )
        added = 0
        for p in paths:
            if p and os.path.splitext(p)[1] in SUPPORTED_PDF_EXTS and p not in self.state.files:
                self.state.files.append(p)
                self.lb.insert(tk.END, p)
                added += 1
        if added:
            self._append_log(f"➕ Added {added} file(s).")

    def on_remove_selected(self) -> None:
        sel = list(self.lb.curselection())
        if not sel:
            return
        sel.reverse()
        for idx in sel:
            path = self.lb.get(idx)
            self.lb.delete(idx)
            if path in self.state.files:
                self.state.files.remove(path)
        self._append_log(f"🗑 Removed {len(sel)} file(s).")

    def on_clear(self) -> None:
        self.lb.delete(0, tk.END)
        self.state.files.clear()
        self._append_log("🧹 Cleared list.")

    def on_choose_outdir(self) -> None:
        chosen = filedialog.askdirectory(title="Choose output folder")
        if chosen:
            self.state.output_dir = chosen
            self.out_var.set(chosen)
            self._append_log(f"📂 Output folder set: {chosen}")

    def on_start(self) -> None:
        if self.state.running:
            return
        if not self.state.files:
            messagebox.showwarning("No files", "Please add at least one PDF.")
            return
        self.state.output_dir = self.out_var.get().strip() or DEFAULT_OUTPUT_DIR
        ensure_dir(self.state.output_dir)

        self.state.running = True
        self.state.cancel_requested = False
        self.state.total_jobs = len(self.state.files)
        self.state.completed_jobs = 0
        self.pb["value"] = 0
        self.status_var.set("Starting…")
        self.eta_var.set("")
        self.btn_start.configure(state=tk.DISABLED)
        self.btn_cancel.configure(state=tk.NORMAL)

        self._append_log(f"🚀 Starting batch — {self.state.total_jobs} file(s).")
        self.worker = PipelineWorker(
            files=self.state.files[:],
            output_dir=self.state.output_dir,
            log_q=self.log_q,
            prog_q=self.prog_q,
            res_q=self.res_q,
            cancel_flag=lambda: self.state.cancel_requested,
        )
        self.worker.start()

    def on_cancel(self) -> None:
        if not self.state.running:
            return
        self.state.cancel_requested = True
        self._append_log("🛑 Cancel requested — finishing current file then stopping…")

    def _on_batch_finished(self) -> None:
        self.state.running = False
        self.btn_start.configure(state=tk.NORMAL)
        self.btn_cancel.configure(state=tk.DISABLED)
        self.status_var.set("Done")
        self._append_log("🎉 All jobs finished.")

    # --- logging helper ---
    def _append_log(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.log_txt.insert(tk.END, f"[{ts}] {msg}\n")
        self.log_txt.see(tk.END)


# ---------------------------
# main()
# ---------------------------

def main():
    ensure_dir(DEFAULT_OUTPUT_DIR)
    root = tk.Tk()
    # Native-looking theme fallback
    try:
        style = ttk.Style()
        if sys.platform.startswith("win"):
            style.theme_use("winnative")
        else:
            style.theme_use("clam")
    except Exception:
        pass

    app = PVJApp(root)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
