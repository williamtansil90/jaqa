from __future__ import annotations

import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

from app import __full_name__, __version__
from app.core.browser_setup import chromium_ready, install_chromium
from app.core.engine import MAX_RECORDED_DELAY_MS, AutomationEngine, payload_to_expectation
from app.core.models import Expectation, ExpectationResult, Step, TestCase, TestSuite, format_delay
from app.core.reporter import export_excel, export_pdf
from app.core.storage import export_json, import_json, load_session, reports_dir, save_session
from app.gui.dialogs import ExpectationDialog, StepDialog, TestCaseDialog, ask_yes_no, bind_tree_style
from app.gui.icon import apply_window_icon
from app.gui.theme import PALETTE, apply_theme

COLUMNS = (
    ("no_tc", "NO. TC", 90),
    ("deskripsi", "Deskripsi", 220),
    ("aplikasi", "Aplikasi", 140),
    ("url", "URL", 220),
    ("username", "Username", 110),
    ("password", "Password", 100),
    ("expected_result", "Expected Result", 220),
    ("status", "Status", 80),
    ("notes", "Catatan", 240),
)


class MainWindow(ctk.CTk):
    def __init__(self) -> None:
        apply_theme()
        super().__init__()
        self.title(f"{__full_name__}  •  v{__version__}")
        self.geometry("1440x860")
        self.minsize(1180, 720)
        self.configure(fg_color=PALETTE["bg"])
        apply_window_icon(self)

        self.suite = load_session() or TestSuite()
        self.events: queue.Queue = queue.Queue()
        self.engine = AutomationEngine(self._on_engine_event)
        self.recording = False
        self.expect_armed = False
        self._selected_id: str | None = None
        self._recording_case_id: str | None = None
        self._last_record_ts: float | None = None
        self._step_sel: str | None = None
        self._exp_sel: str | None = None

        self._build()
        self._refresh_table()
        self._set_status("Siap. Tambah test case, lalu rekam langkah pengguna.")
        self.after(200, self._pump_events)
        self.after(400, self._ensure_browser)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build(self) -> None:
        header = ctk.CTkFrame(self, fg_color=PALETTE["surface"], corner_radius=0, height=72)
        header.pack(fill="x")
        header.pack_propagate(False)
        brand = ctk.CTkFrame(header, fg_color="transparent")
        brand.pack(side="left", padx=20, pady=12)
        ctk.CTkLabel(brand, text="JAQA", font=ctk.CTkFont(size=26, weight="bold"), text_color=PALETTE["gold"]).pack(anchor="w")
        ctk.CTkLabel(brand, text="Jalin Automate QA  —  SIT Otomatis", font=ctk.CTkFont(size=12), text_color=PALETTE["muted"]).pack(anchor="w")

        self.rec_badge = ctk.CTkLabel(header, text="", font=ctk.CTkFont(size=13, weight="bold"), text_color=PALETTE["nok"])
        self.rec_badge.pack(side="right", padx=20)

        toolbar = ctk.CTkFrame(self, fg_color=PALETTE["surface_alt"], corner_radius=0)
        toolbar.pack(fill="x")
        groups = [
            ("Test Case", [
                ("Tambah TC", self.add_case, PALETTE["accent"]),
                ("Ubah", self.edit_case, PALETTE["surface"]),
                ("Hapus", self.delete_case, PALETTE["surface"]),
            ]),
            ("Rekam", [
                ("RECORD", self.toggle_record, "#B91C1C"),
                ("Expected Element", self.toggle_expect, "#C2410C"),
            ]),
            ("Jalankan", [
                ("Run Baris Ini", self.run_selected, PALETTE["accent"]),
                ("Run Sampai Baris Ini", self.run_until, PALETTE["accent"]),
                ("Run All", self.run_all, PALETTE["accent"]),
                ("Stop", self.stop_engine, PALETTE["surface"]),
            ]),
            ("Berkas", [
                ("Impor JSON", self.import_json, PALETTE["surface"]),
                ("Ekspor JSON", self.export_json_file, PALETTE["surface"]),
                ("Ekspor Excel", self.export_excel_file, PALETTE["surface"]),
                ("Ekspor PDF", self.export_pdf_file, PALETTE["surface"]),
            ]),
        ]
        for title, buttons in groups:
            box = ctk.CTkFrame(toolbar, fg_color="transparent")
            box.pack(side="left", padx=10, pady=8)
            ctk.CTkLabel(box, text=title.upper(), font=ctk.CTkFont(size=10, weight="bold"), text_color=PALETTE["muted"]).pack(anchor="w")
            row = ctk.CTkFrame(box, fg_color="transparent")
            row.pack(anchor="w")
            for text, cmd, color in buttons:
                hover = PALETTE["accent_hover"] if color == PALETTE["accent"] else PALETTE["border"]
                ctk.CTkButton(
                    row,
                    text=text,
                    command=cmd,
                    fg_color=color,
                    hover_color=hover,
                    width=130 if text != "RECORD" else 100,
                    height=30,
                    font=ctk.CTkFont(size=12, weight="bold" if text in {"RECORD", "Run All"} else "normal"),
                ).pack(side="left", padx=(0, 6))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=10)

        table_wrap = ctk.CTkFrame(body, fg_color=PALETTE["surface"], corner_radius=10)
        table_wrap.pack(fill="both", expand=True)
        inner = tk.Frame(table_wrap, bg=PALETTE["surface"])
        inner.pack(fill="both", expand=True, padx=8, pady=8)

        self.tree = ttk.Treeview(inner, columns=[c[0] for c in COLUMNS], show="headings", selectmode="browse")
        bind_tree_style(self.tree)
        for key, title, width in COLUMNS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=70, stretch=True)
        yscroll = ttk.Scrollbar(inner, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(inner, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        inner.grid_rowconfigure(0, weight=1)
        inner.grid_columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())
        self.tree.bind("<Double-1>", lambda _e: self.edit_case())

        detail = ctk.CTkTabview(body, fg_color=PALETTE["surface"], segmented_button_selected_color=PALETTE["accent"], height=300)
        detail.pack(fill="x", pady=(10, 0))
        self.tab_steps = detail.add("Langkah Terekam")
        self.tab_exp = detail.add("Expected Result")
        self.tab_run = detail.add("Hasil Run")

        self.steps_tree = self._make_list_tree(
            self.tab_steps,
            (
                ("no", "#", 44),
                ("tipe", "Tipe", 110),
                ("ket", "Keterangan", 280),
                ("delay", "Jeda", 90),
                ("selector", "Selector", 180),
                ("nilai", "Nilai", 140),
            ),
            self._on_step_select,
            self.edit_step,
        )
        step_btns = (
            ("Ubah Langkah", self.edit_step),
            ("Tambah Delay", self.add_delay_step),
            ("Naik", self.move_step_up),
            ("Turun", self.move_step_down),
            ("Hapus Langkah", self.delete_step),
        )
        self._pack_list_buttons(self.tab_steps, step_btns)

        self.exp_tree = self._make_list_tree(
            self.tab_exp,
            (
                ("no", "#", 44),
                ("label", "Label", 180),
                ("kind", "Jenis", 110),
                ("match", "Banding", 110),
                ("nilai", "Nilai expected", 200),
                ("after", "Periksa setelah", 130),
            ),
            self._on_exp_select,
            self.edit_expectation,
        )
        exp_btns = (
            ("Tambah Expected", self.add_expectation),
            ("Ubah", self.edit_expectation),
            ("Naik", self.move_expectation_up),
            ("Turun", self.move_expectation_down),
            ("Hapus", self.delete_expectation),
        )
        self._pack_list_buttons(self.tab_exp, exp_btns)

        self.run_box = ctk.CTkTextbox(self.tab_run, fg_color=PALETTE["surface_alt"], wrap="word")
        self.run_box.pack(fill="both", expand=True, padx=6, pady=6)

        status = ctk.CTkFrame(self, fg_color=PALETTE["surface"], corner_radius=0, height=32)
        status.pack(fill="x", side="bottom")
        status.pack_propagate(False)
        self.status_var = tk.StringVar(value="")
        ctk.CTkLabel(status, textvariable=self.status_var, anchor="w", text_color=PALETTE["muted"]).pack(fill="x", padx=16)

    def _make_list_tree(self, parent, columns, on_select, on_double) -> ttk.Treeview:
        wrap = tk.Frame(parent, bg=PALETTE["surface"])
        wrap.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        tree = ttk.Treeview(wrap, columns=[c[0] for c in columns], show="headings", selectmode="browse")
        bind_tree_style(tree)
        for key, title, width in columns:
            tree.heading(key, text=title)
            tree.column(key, width=width, minwidth=40, stretch=True)
        yscroll = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=yscroll.set)
        tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")
        tree.bind("<<TreeviewSelect>>", lambda _e: on_select())
        tree.bind("<Double-1>", lambda _e: on_double())
        return tree

    def _pack_list_buttons(self, parent, items: tuple) -> None:
        box = ctk.CTkFrame(parent, fg_color="transparent", width=150)
        box.pack(side="right", fill="y", padx=6, pady=6)
        for text, cmd in items:
            ctk.CTkButton(box, text=text, command=cmd, fg_color=PALETTE["surface_alt"], hover_color=PALETTE["border"], width=140, height=28).pack(fill="x", pady=3)

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _selected_case(self) -> TestCase | None:
        item = self._selected_iid()
        if not item:
            return None
        return next((tc for tc in self.suite.test_cases if tc.id == item), None)

    def _selected_iid(self) -> str | None:
        sel = self.tree.selection()
        return sel[0] if sel else self._selected_id

    def _on_select(self) -> None:
        sel = self.tree.selection()
        if sel:
            self._selected_id = sel[0]
        self._refresh_details()

    def _case_values(self, case: TestCase) -> tuple[str, ...]:
        masked = "•" * min(len(case.password), 10) if case.password else ""
        expected = case.expected_result
        if case.expectations:
            extra = "; ".join(item.summary() for item in case.expectations[:3])
            expected = (expected + " | " if expected else "") + extra
            if len(case.expectations) > 3:
                expected += f" (+{len(case.expectations) - 3})"
        return (
            case.no_tc,
            case.deskripsi,
            case.aplikasi,
            case.url,
            case.username,
            masked,
            expected,
            case.status or "—",
            case.notes,
        )

    def _tag_for(self, case: TestCase, index: int) -> str:
        if case.status == "RUNNING":
            return "run"
        if case.status == "OK":
            return "ok"
        if case.status == "NOK":
            return "nok"
        return "odd" if index % 2 else "even"

    def _refresh_table(self, keep_selection: bool = True) -> None:
        selected = self._selected_iid() if keep_selection else None
        self.tree.delete(*self.tree.get_children())
        for index, case in enumerate(self.suite.test_cases):
            self.tree.insert("", "end", iid=case.id, values=self._case_values(case), tags=(self._tag_for(case, index),))
        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected)
            self.tree.see(selected)
        elif self.suite.test_cases:
            last = self.suite.test_cases[-1].id
            self.tree.selection_set(last)
            self._selected_id = last
        self._refresh_details()
        self._autosave()

    def _refresh_details(self) -> None:
        case = self._selected_case()
        step_keep = self._step_sel or (self.steps_tree.selection()[0] if self.steps_tree.selection() else None)
        exp_keep = self._exp_sel or (self.exp_tree.selection()[0] if self.exp_tree.selection() else None)
        self.steps_tree.delete(*self.steps_tree.get_children())
        self.exp_tree.delete(*self.exp_tree.get_children())
        self.run_box.configure(state="normal")
        self.run_box.delete("1.0", "end")
        if not case:
            self.run_box.insert("1.0", "Belum ada hasil run.")
            return
        for index, step in enumerate(case.steps, start=1):
            delay = format_delay(step.delay_ms) if step.type != "wait" else "—"
            nilai = step.value if step.type != "goto" else step.url
            self.steps_tree.insert(
                "",
                "end",
                iid=step.id,
                values=(index, step.type_label(), step.summary(), delay, step.selector, nilai),
                tags=("odd" if index % 2 else "even",),
            )
        for index, item in enumerate(case.expectations, start=1):
            after = f"Langkah {item.after_step}" if item.after_step else "Akhir"
            self.exp_tree.insert(
                "",
                "end",
                iid=item.id,
                values=(index, item.label or item.selector, item.kind, item.match, item.expected_value, after),
                tags=("odd" if index % 2 else "even",),
            )
        if step_keep and self.steps_tree.exists(step_keep):
            self.steps_tree.selection_set(step_keep)
            self.steps_tree.see(step_keep)
        if exp_keep and self.exp_tree.exists(exp_keep):
            self.exp_tree.selection_set(exp_keep)
            self.exp_tree.see(exp_keep)
        if case.status or case.expectation_results:
            header = f"Status: {case.status or '—'}   •   {case.last_run_at or ''}\n{case.notes}\n\n"
            details = []
            for item in case.expectation_results:
                details.append(
                    f"[{item.status}] {item.label or item.expectation_id}\n    diharapkan: {item.expected}\n    aktual    : {item.actual}\n    {item.reason}"
                )
            self.run_box.insert("1.0", header + ("\n\n".join(details) if details else ""))
        else:
            self.run_box.insert("1.0", "Belum dijalankan.")

    def _autosave(self) -> None:
        try:
            save_session(self.suite)
        except OSError:
            pass

    def _require_case(self) -> TestCase | None:
        case = self._selected_case()
        if not case:
            messagebox.showinfo("JAQA", "Pilih test case terlebih dahulu.")
        return case

    def add_case(self) -> None:
        if self.engine.busy:
            messagebox.showinfo("JAQA", "Selesaikan rekaman/run terlebih dahulu.")
            return
        dialog = TestCaseDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self.suite.test_cases.append(dialog.result)
            self._selected_id = dialog.result.id
            self._refresh_table()
            self._set_status(f"Test case {dialog.result.no_tc} ditambahkan. Klik RECORD untuk merekam.")

    def edit_case(self) -> None:
        case = self._require_case()
        if not case or self.recording:
            return
        dialog = TestCaseDialog(self, case)
        self.wait_window(dialog)
        if dialog.result:
            self._refresh_table()
            self._set_status(f"Test case {case.no_tc} diubah.")

    def delete_case(self) -> None:
        case = self._require_case()
        if not case or self.engine.busy:
            return
        if not ask_yes_no(self, "Hapus Test Case", f"Hapus {case.no_tc} beserta rekaman dan expected-nya?"):
            return
        self.suite.test_cases = [item for item in self.suite.test_cases if item.id != case.id]
        self._selected_id = None
        self._refresh_table(keep_selection=False)
        self._set_status(f"{case.no_tc} dihapus.")

    def _can_edit_lists(self) -> bool:
        if self.engine.busy:
            messagebox.showinfo("JAQA", "Selesaikan rekaman/run terlebih dahulu.")
            return False
        return self._require_case() is not None

    def _on_step_select(self) -> None:
        sel = self.steps_tree.selection()
        if sel:
            self._step_sel = sel[0]

    def _on_exp_select(self) -> None:
        sel = self.exp_tree.selection()
        if sel:
            self._exp_sel = sel[0]

    def _selected_step(self) -> tuple[TestCase, int, Step] | None:
        case = self._selected_case()
        if not case:
            return None
        iid = self._step_sel or (self.steps_tree.selection()[0] if self.steps_tree.selection() else None)
        if not iid:
            return None
        for index, step in enumerate(case.steps):
            if step.id == iid:
                return case, index, step
        return None

    def _selected_expectation(self) -> tuple[TestCase, int, Expectation] | None:
        case = self._selected_case()
        if not case:
            return None
        iid = self._exp_sel or (self.exp_tree.selection()[0] if self.exp_tree.selection() else None)
        if not iid:
            return None
        for index, item in enumerate(case.expectations):
            if item.id == iid:
                return case, index, item
        return None

    def _remap_after_insert(self, case: TestCase, inserted_at: int) -> None:
        for item in case.expectations:
            if item.after_step >= inserted_at + 1:
                item.after_step += 1

    def _remap_after_delete(self, case: TestCase, deleted_at: int) -> None:
        target = deleted_at + 1
        for item in case.expectations:
            if item.after_step == target:
                item.after_step = deleted_at
            elif item.after_step > target:
                item.after_step -= 1

    def _remap_after_move(self, case: TestCase, src: int, dest: int) -> None:
        src_n, dest_n = src + 1, dest + 1
        for item in case.expectations:
            point = item.after_step
            if point == 0:
                continue
            if src < dest:
                if point == src_n:
                    item.after_step = dest_n
                elif src_n < point <= dest_n:
                    item.after_step -= 1
            elif dest < src:
                if point == src_n:
                    item.after_step = dest_n
                elif dest_n <= point < src_n:
                    item.after_step += 1

    def edit_step(self) -> None:
        if not self._can_edit_lists():
            return
        selected = self._selected_step()
        if not selected:
            messagebox.showinfo("JAQA", "Pilih langkah yang akan diubah.")
            return
        _case, _index, step = selected
        dialog = StepDialog(self, step)
        self.wait_window(dialog)
        if dialog.result:
            self._refresh_table()
            self._set_status(f"Langkah diubah: {step.summary()}")

    def add_delay_step(self) -> None:
        if not self._can_edit_lists():
            return
        case = self._selected_case()
        if not case:
            return
        dialog = StepDialog(self, delay_only=True)
        self.wait_window(dialog)
        if not dialog.result:
            return
        selected = self._selected_step()
        insert_at = selected[1] + 1 if selected else len(case.steps)
        case.steps.insert(insert_at, dialog.result)
        self._remap_after_insert(case, insert_at)
        self._step_sel = dialog.result.id
        self._refresh_table()
        self._set_status(f"Delay ditambahkan: {dialog.result.summary()}")

    def delete_step(self) -> None:
        if not self._can_edit_lists():
            return
        selected = self._selected_step()
        if not selected:
            messagebox.showinfo("JAQA", "Pilih langkah yang akan dihapus.")
            return
        case, index, step = selected
        if not ask_yes_no(self, "Hapus Langkah", f"Hapus langkah: {step.summary()}?"):
            return
        case.steps.pop(index)
        self._remap_after_delete(case, index)
        self._step_sel = case.steps[min(index, len(case.steps) - 1)].id if case.steps else None
        self._refresh_table()

    def move_step_up(self) -> None:
        self._move_step(-1)

    def move_step_down(self) -> None:
        self._move_step(1)

    def _move_step(self, delta: int) -> None:
        if not self._can_edit_lists():
            return
        selected = self._selected_step()
        if not selected:
            return
        case, index, step = selected
        dest = index + delta
        if dest < 0 or dest >= len(case.steps):
            return
        case.steps[index], case.steps[dest] = case.steps[dest], case.steps[index]
        self._remap_after_move(case, index, dest)
        self._step_sel = step.id
        self._refresh_table()

    def add_expectation(self) -> None:
        if not self._can_edit_lists():
            return
        case = self._selected_case()
        if not case:
            return
        dialog = ExpectationDialog(self, {}, step_count=len(case.steps))
        self.wait_window(dialog)
        if not dialog.result:
            return
        if not dialog.result.after_step:
            dialog.result.after_step = len(case.steps)
        case.expectations.append(dialog.result)
        self._exp_sel = dialog.result.id
        self._refresh_table()
        self._set_status(f"Expected ditambahkan: {dialog.result.summary()}")

    def edit_expectation(self) -> None:
        if not self._can_edit_lists():
            return
        selected = self._selected_expectation()
        if not selected:
            messagebox.showinfo("JAQA", "Pilih expected result yang akan diubah.")
            return
        case, _index, item = selected
        dialog = ExpectationDialog(self, {}, existing=item, step_count=len(case.steps))
        self.wait_window(dialog)
        if dialog.result:
            self._refresh_table()
            self._set_status(f"Expected diubah: {item.summary()}")

    def delete_expectation(self) -> None:
        if not self._can_edit_lists():
            return
        selected = self._selected_expectation()
        if not selected:
            messagebox.showinfo("JAQA", "Pilih expected result yang akan dihapus.")
            return
        case, index, item = selected
        if not ask_yes_no(self, "Hapus Expected", f"Hapus expected: {item.summary()}?"):
            return
        case.expectations.pop(index)
        self._exp_sel = case.expectations[min(index, len(case.expectations) - 1)].id if case.expectations else None
        self._refresh_table()

    def move_expectation_up(self) -> None:
        self._move_expectation(-1)

    def move_expectation_down(self) -> None:
        self._move_expectation(1)

    def _move_expectation(self, delta: int) -> None:
        if not self._can_edit_lists():
            return
        selected = self._selected_expectation()
        if not selected:
            return
        case, index, item = selected
        dest = index + delta
        if dest < 0 or dest >= len(case.expectations):
            return
        case.expectations[index], case.expectations[dest] = case.expectations[dest], case.expectations[index]
        self._exp_sel = item.id
        self._refresh_table()

    def toggle_record(self) -> None:
        if self.recording:
            self.engine.stop()
            self._set_status("Menghentikan rekaman...")
            return
        case = self._require_case()
        if not case:
            return
        if not case.url:
            messagebox.showwarning("JAQA", "Isi URL pada test case sebelum merekam.")
            return
        try:
            self.engine.start_record(case)
        except RuntimeError as exc:
            messagebox.showerror("JAQA", str(exc))
            return
        self.recording = True
        self.expect_armed = False
        self._recording_case_id = case.id
        self._last_record_ts = time.monotonic()
        self.rec_badge.configure(text="● RECORDING")
        self._set_status(f"Merekam {case.no_tc}. Lakukan langkah di browser. Klik Expected Element untuk menandai hasil.")

    def toggle_expect(self) -> None:
        if not self.recording:
            messagebox.showinfo("JAQA", "Expected Element hanya tersedia saat RECORD berlangsung.")
            return
        self.expect_armed = not self.expect_armed
        self.engine.set_expect_mode(self.expect_armed)
        if self.expect_armed:
            self.rec_badge.configure(text="● EXPECTED MODE")
            self._set_status("Mode Expected aktif. Klik elemen di browser, lalu isi nilai yang diharapkan.")
        else:
            self.rec_badge.configure(text="● RECORDING")
            self._set_status("Kembali merekam langkah pengguna.")

    def _run(self, cases: list[TestCase]) -> None:
        if self.engine.busy:
            messagebox.showinfo("JAQA", "Mesin otomasi sedang berjalan.")
            return
        if not cases:
            messagebox.showinfo("JAQA", "Tidak ada test case yang dipilih.")
            return
        for case in cases:
            case.status = "RUNNING"
            case.notes = "Sedang dijalankan..."
            case.expectation_results = []
        self._refresh_table()
        try:
            self.engine.run_cases(cases)
        except RuntimeError as exc:
            messagebox.showerror("JAQA", str(exc))
            return
        self._set_status(f"Menjalankan {len(cases)} test case...")

    def run_selected(self) -> None:
        case = self._require_case()
        if case:
            self._run([case])

    def run_until(self) -> None:
        case = self._require_case()
        if not case:
            return
        idx = self.suite.index_of(case.id)
        self._run(self.suite.test_cases[: idx + 1])

    def run_all(self) -> None:
        self._run(list(self.suite.test_cases))

    def stop_engine(self) -> None:
        if self.engine.busy:
            self.engine.stop()
            self._set_status("Meminta berhenti...")

    def import_json(self) -> None:
        if self.engine.busy:
            return
        path = filedialog.askopenfilename(title="Impor JSON JAQA", filetypes=[("JSON", "*.json"), ("Semua", "*.*")])
        if not path:
            return
        try:
            imported = import_json(path)
        except Exception as exc:
            messagebox.showerror("JAQA", f"Gagal impor JSON:\n{exc}")
            return
        if self.suite.test_cases and not ask_yes_no(self, "Impor JSON", "Ganti suite saat ini dengan isi file JSON?"):
            return
        self.suite = imported
        self._selected_id = None
        self._refresh_table(keep_selection=False)
        self._set_status(f"Diimpor {len(self.suite.test_cases)} test case dari {Path(path).name}")

    def export_json_file(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Ekspor JSON",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile="jaqa_testcases.json",
        )
        if not path:
            return
        export_json(self.suite, path)
        self._set_status(f"JSON tersimpan: {path}")

    def export_excel_file(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Ekspor Excel",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialdir=str(reports_dir()),
            initialfile="JAQA_Laporan_SIT.xlsx",
        )
        if not path:
            return
        export_excel(self.suite, path)
        self._set_status(f"Excel tersimpan: {path}")

    def export_pdf_file(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Ekspor PDF",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            initialdir=str(reports_dir()),
            initialfile="JAQA_Laporan_SIT.pdf",
        )
        if not path:
            return
        export_pdf(self.suite, path)
        self._set_status(f"PDF tersimpan: {path}")

    def _on_engine_event(self, kind: str, payload: dict) -> None:
        self.events.put((kind, payload))

    def _pump_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                self._handle_event(kind, payload)
        except queue.Empty:
            pass
        self.after(120, self._pump_events)

    def _recording_case(self) -> TestCase | None:
        if self._recording_case_id:
            return next((tc for tc in self.suite.test_cases if tc.id == self._recording_case_id), None)
        return self._selected_case()

    def _handle_event(self, kind: str, payload: dict) -> None:
        if kind == "info":
            self._set_status(payload.get("message") or "")
            return
        if kind == "ready":
            self._set_status(payload.get("message") or "Siap.")
            return
        if kind == "action":
            case = self._recording_case()
            if not case:
                return
            step = Step.from_dict(payload.get("step") or payload)
            if step.type == "goto" and case.steps and case.steps[-1].type == "goto" and case.steps[-1].url == step.url:
                return
            now = time.monotonic()
            if case.steps and self._last_record_ts is not None:
                gap = int((now - self._last_record_ts) * 1000)
                case.steps[-1].delay_ms = max(0, min(gap, MAX_RECORDED_DELAY_MS))
            self._last_record_ts = now
            case.steps.append(step)
            self._step_sel = step.id
            self._refresh_details()
            self._autosave()
            jeda = format_delay(case.steps[-2].delay_ms) if len(case.steps) > 1 else "0 ms"
            self._set_status(f"Terekam: {step.summary()}  •  jeda sebelumnya {jeda}")
        elif kind == "expect_pick":
            case = self._recording_case()
            if case and case.steps and self._last_record_ts is not None:
                gap = int((time.monotonic() - self._last_record_ts) * 1000)
                case.steps[-1].delay_ms = max(case.steps[-1].delay_ms, min(gap, MAX_RECORDED_DELAY_MS))
            self._add_expectation_from_pick(payload.get("payload") or payload)
        elif kind == "record_started":
            self._set_status("Browser rekaman siap.")
        elif kind == "record_stopped":
            self.recording = False
            self.expect_armed = False
            self._recording_case_id = None
            self._last_record_ts = None
            self.rec_badge.configure(text="")
            self._refresh_table()
            self._set_status("Rekaman selesai. Jeda antar langkah tersimpan dan bisa diedit.")
        elif kind == "case_started":
            case = next((tc for tc in self.suite.test_cases if tc.id == payload.get("case_id")), None)
            if case:
                case.status = "RUNNING"
                case.notes = "Sedang dijalankan..."
                self._refresh_table()
            self._set_status(f"Menjalankan {payload.get('no_tc')}...")
        elif kind == "case_finished":
            case = next((tc for tc in self.suite.test_cases if tc.id == payload.get("case_id")), None)
            if case:
                case.status = payload.get("status") or "NOK"
                case.notes = payload.get("notes", "")
                case.last_run_at = payload.get("last_run_at", "")
                case.expectation_results = [ExpectationResult.from_dict(item) for item in payload.get("expectation_results") or []]
                self._refresh_table()
        elif kind == "run_finished":
            self._set_status("Eksekusi selesai.")
            self._autosave()
        elif kind == "run_aborted":
            self._set_status("Eksekusi dibatalkan.")
        elif kind == "error":
            messagebox.showerror("JAQA", payload.get("message") or "Terjadi kesalahan.")
            self.recording = False
            self.expect_armed = False
            self._recording_case_id = None
            self._last_record_ts = None
            self.rec_badge.configure(text="")
            self._set_status(payload.get("message") or "Error")

    def _add_expectation_from_pick(self, data: dict) -> None:
        case = self._recording_case()
        if not case:
            return
        preview = payload_to_expectation(data, after_step=len(case.steps))
        dialog = ExpectationDialog(self, preview, step_count=len(case.steps))
        self.wait_window(dialog)
        if not dialog.result:
            return
        expectation = dialog.result
        if not expectation.after_step:
            expectation.after_step = len(case.steps)
        expectation.tag = preview.get("tag", "") or expectation.tag
        expectation.sample_text = preview.get("sample_text", "") or expectation.sample_text
        case.expectations.append(expectation)
        self._exp_sel = expectation.id
        self._refresh_table()
        self._set_status(f"Expected ditambahkan: {expectation.summary()}")

    def _ensure_browser(self) -> None:
        def worker() -> None:
            if chromium_ready():
                self.events.put(("ready", {"message": "Browser otomasi siap."}))
                return
            self.events.put(("info", {"message": "Mengunduh Chromium untuk otomasi (sekali saja)..."}))
            try:
                install_chromium()
                self.events.put(("ready", {"message": "Chromium siap. JAQA siap merekam dan menjalankan test."}))
            except Exception as exc:
                self.events.put(("error", {"message": f"Gagal menyiapkan browser Playwright:\n{exc}\n\nJalankan: python -m playwright install chromium"}))

        threading.Thread(target=worker, daemon=True, name="jaqa-browser-setup").start()

    def _on_close(self) -> None:
        if self.engine.busy:
            self.engine.stop()
        self._autosave()
        self.destroy()


def run_app() -> None:
    if sys.platform == "win32":
        try:
            from ctypes import windll

            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    app = MainWindow()
    app.mainloop()
