from __future__ import annotations

import json
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

from app import __about__, __full_name__, __version__
from app.core.browser_setup import chromium_ready, install_chromium
from app.core.browser_session import BrowserImportSource, fetch_cookies, fetch_storage_state, warnings_text
from app.core.engine import MAX_RECORDED_DELAY_MS, AutomationEngine, payload_to_expectation
from app.core.models import (
    Expectation,
    ExpectationResult,
    Step,
    EXPECT_LIST_COLUMNS,
    STEP_LIST_COLUMNS,
    TC_LIST_COLUMNS,
    TestCase,
    TestSuite,
    format_delay,
)
from app.core.reporter import export_excel, export_pdf, export_tc_excel, import_tc_excel
from app.core.storage import export_json, import_json, last_config_path, load_session, remember_config_path, reports_dir, save_session
from app.gui.dialogs import AboutDialog, BrowserImportDialog, ExpectationDialog, StepDialog, TestCaseDialog, ask_yes_no, bind_tree_style
from app.gui.icon import apply_window_icon, make_check_icons
from app.gui.theme import PALETTE, apply_theme

_TC_WIDTHS = {
    "aktif": 52,
    "no_tc": 90,
    "deskripsi": 200,
    "aplikasi": 130,
    "url": 200,
    "username": 110,
    "password": 100,
    "expected_result": 200,
    "expectation": 200,
    "status": 80,
    "notes": 220,
}

_STEP_WIDTHS = {
    "aktif": 52,
    "no": 44,
    "tipe": 110,
    "ket": 260,
    "delay": 90,
    "selector": 170,
    "nilai": 130,
}

_EXP_WIDTHS = {
    "aktif": 52,
    "no": 44,
    "label": 170,
    "kind": 100,
    "match": 100,
    "nilai": 180,
    "after": 120,
}

COLUMNS = tuple((key, label, _TC_WIDTHS[key]) for key, label in TC_LIST_COLUMNS)

TC_EDITABLE = frozenset({"no_tc", "deskripsi", "aplikasi", "url", "username", "password", "expected_result", "notes"})


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
        self.config_path: Path | None = None
        self._checked_ids: set[str] = set()
        self._checked_step_ids: set[str] = set()
        self._checked_exp_ids: set[str] = set()
        self._drag_iid: str | None = None
        self._drag_y = 0
        self._dragging = False
        self._tc_context_menu: tk.Menu | None = None
        self._cell_edit: dict | None = None
        self._step_context_menu: tk.Menu | None = None
        self._step_clipboard: list[Step] = []
        self._step_drag_iid: str | None = None
        self._step_drag_y = 0
        self._step_dragging = False
        self._exp_context_menu: tk.Menu | None = None
        self._exp_clipboard: list[Expectation] = []
        self._tc_search = tk.StringVar()
        self._step_search = tk.StringVar()
        self._exp_search = tk.StringVar()

        self._build()
        self._bind_search_refresh(self._tc_search, lambda: self._refresh_table(keep_selection=True, autosave=False))
        self._bind_search_refresh(self._step_search, self._refresh_details)
        self._bind_search_refresh(self._exp_search, self._refresh_details)
        self._refresh_table()
        self._set_status("Siap. Tambah test case, lalu rekam langkah pengguna.")
        self._sync_title()
        self.after(200, self._pump_events)
        self.after(400, self._ensure_browser)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build(self) -> None:
        self._build_menubar()
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
            ("left", "Test Case", [
                ("Add TC", self.add_case, PALETTE["accent"]),
                ("Edit TC", self.edit_case, PALETTE["surface"]),
                ("Delete TC", self.delete_case, PALETTE["surface"]),
            ]),
            ("left", "Jalankan", [
                ("Single Run", self.run_selected, PALETTE["accent"]),
                ("Run Until", self.run_until, PALETTE["accent"]),
                ("Run All", self.run_all, PALETTE["accent"]),
            ]),
            ("right", "STATUS", [
                ("ENABLE", self.enable_selected, PALETTE["ok"]),
                ("DISABLE", self.disable_selected, "#475569"),
            ]),
            ("right", "Rekam", [
                ("RECORD", self.toggle_record, "#B91C1C"),
                ("EXPECTED RESULT", self.toggle_expect, "#C2410C"),
                ("Stop", self.stop_engine, PALETTE["surface"]),
            ]),
        ]
        for side, title, buttons in groups:
            box = ctk.CTkFrame(toolbar, fg_color="transparent")
            box.pack(side=side, padx=10, pady=8)
            ctk.CTkLabel(box, text=title.upper(), font=ctk.CTkFont(size=10, weight="bold"), text_color=PALETTE["muted"]).pack(anchor="w")
            row = ctk.CTkFrame(box, fg_color="transparent")
            row.pack(anchor="w")
            for text, cmd, color in buttons:
                hover = PALETTE["accent_hover"] if color == PALETTE["accent"] else PALETTE["border"]
                width = 150 if text == "EXPECTED RESULT" else 100 if text == "RECORD" else 130
                ctk.CTkButton(
                    row,
                    text=text,
                    command=cmd,
                    fg_color=color,
                    hover_color=hover,
                    width=width,
                    height=30,
                    font=ctk.CTkFont(size=12, weight="bold" if text in {"RECORD", "Run All", "EXPECTED RESULT"} else "normal"),
                ).pack(side="left", padx=(0, 6))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=10)

        table_wrap = ctk.CTkFrame(body, fg_color=PALETTE["surface"], corner_radius=10)
        table_wrap.pack(fill="both", expand=True)
        inner = tk.Frame(table_wrap, bg=PALETTE["surface"])
        inner.pack(fill="both", expand=True, padx=8, pady=8)

        self.check_off, self.check_on = make_check_icons()
        tc_search = tk.Frame(inner, bg=PALETTE["surface"])
        tc_search.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self._build_search_box(tc_search, self._tc_search)
        self.tree = ttk.Treeview(inner, columns=[c[0] for c in COLUMNS], show="tree headings", selectmode="extended")
        bind_tree_style(self.tree)
        style = ttk.Style(self.tree)
        style.layout(
            "JAQA.Treeview.Item",
            [
                (
                    "Treeitem.padding",
                    {
                        "sticky": "nswe",
                        "children": [
                            ("Treeitem.image", {"side": "left", "sticky": ""}),
                            ("Treeitem.text", {"side": "left", "sticky": ""}),
                        ],
                    },
                )
            ],
        )
        self.tree.heading("#0", text="☐", command=self._toggle_check_all)
        self.tree.column("#0", width=40, minwidth=36, stretch=False, anchor="center")
        for key, title, width in COLUMNS:
            self.tree.heading(key, text=title)
            stretch = key != "aktif"
            self.tree.column(key, width=width, minwidth=48 if key == "aktif" else 70, stretch=stretch, anchor="center" if key == "aktif" else "w")
        yscroll = ttk.Scrollbar(inner, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(inner, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=1, column=0, sticky="nsew")
        yscroll.grid(row=1, column=1, sticky="ns")
        xscroll.grid(row=2, column=0, sticky="ew")
        inner.grid_rowconfigure(1, weight=1)
        inner.grid_columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())
        self.tree.bind("<Button-1>", self._on_tree_click, add="+")
        self.tree.bind("<ButtonPress-1>", self._on_tc_drag_start, add="+")
        self.tree.bind("<B1-Motion>", self._on_tc_drag_motion, add="+")
        self.tree.bind("<ButtonRelease-1>", self._on_tc_drag_drop, add="+")
        self.tree.bind("<Double-1>", self._on_tree_double)
        self.tree.bind("<Button-3>", self._on_tc_context_menu)
        self._build_tc_context_menu()

        detail = ctk.CTkTabview(body, fg_color=PALETTE["surface"], segmented_button_selected_color=PALETTE["accent"], height=300)
        detail.pack(fill="x", pady=(10, 0))
        self.tab_steps = detail.add("Record Step")
        self.tab_exp = detail.add("Expected Result")
        self.tab_run = detail.add("Test Result")

        self.steps_tree, steps_wrap = self._make_list_tree(
            self.tab_steps,
            tuple((key, label, _STEP_WIDTHS[key]) for key, label in STEP_LIST_COLUMNS),
            self._on_step_select,
            self.edit_step,
            "_checked_step_ids",
            selectmode="extended",
            on_active_toggle=self._toggle_step_enabled,
            search_var=self._step_search,
        )
        self.steps_tree.unbind("<Double-1>")
        self.steps_tree.bind("<ButtonPress-1>", self._on_step_drag_start, add="+")
        self.steps_tree.bind("<B1-Motion>", self._on_step_drag_motion, add="+")
        self.steps_tree.bind("<ButtonRelease-1>", self._on_step_drag_drop, add="+")
        self.steps_tree.bind("<Double-1>", self._on_step_double)
        self.steps_tree.bind("<Button-3>", self._on_step_context_menu)
        steps_wrap.bind("<Button-3>", self._on_step_context_menu)
        self.tab_steps.bind("<Button-3>", self._on_step_context_menu)
        self._bind_step_clipboard_keys()
        self._build_step_context_menu()
        step_btns = (
            ("Edit Step", self.edit_step),
            ("Add Delay", self.add_delay_step),
            ("Move Up", self.move_step_up),
            ("Move Down", self.move_step_down),
        )
        self._pack_list_buttons(self.tab_steps, step_btns)

        self.exp_tree, exp_wrap = self._make_list_tree(
            self.tab_exp,
            tuple((key, label, _EXP_WIDTHS[key]) for key, label in EXPECT_LIST_COLUMNS),
            self._on_exp_select,
            self.edit_expectation,
            "_checked_exp_ids",
            selectmode="extended",
            on_active_toggle=self._toggle_expectation_enabled,
            search_var=self._exp_search,
        )
        self.exp_tree.unbind("<Double-1>")
        self.exp_tree.configure(selectmode="extended")
        self.exp_tree.bind("<Double-1>", self._on_exp_double)
        self.exp_tree.bind("<Button-3>", self._on_exp_context_menu)
        exp_wrap.bind("<Button-3>", self._on_exp_context_menu)
        self.tab_exp.bind("<Button-3>", self._on_exp_context_menu)
        self._bind_exp_clipboard_keys()
        self._build_exp_context_menu()
        exp_btns = (
            ("Add Expected", self.add_expectation),
            ("Edit Expected", self.edit_expectation),
            ("Move Up", self.move_expectation_up),
            ("Move Down", self.move_expectation_down),
        )
        self._pack_list_buttons(self.tab_exp, exp_btns)

        self.run_box = ctk.CTkTextbox(self.tab_run, fg_color=PALETTE["surface_alt"], wrap="word")
        self.run_box.pack(fill="both", expand=True, padx=6, pady=6)

        status = ctk.CTkFrame(self, fg_color=PALETTE["surface"], corner_radius=0, height=32)
        status.pack(fill="x", side="bottom")
        status.pack_propagate(False)
        self.status_var = tk.StringVar(value="")
        ctk.CTkLabel(status, textvariable=self.status_var, anchor="w", text_color=PALETTE["muted"]).pack(fill="x", padx=16)

    def _menu_style(self) -> dict:
        return {
            "tearoff": 0,
            "bg": PALETTE["surface"],
            "fg": PALETTE["text"],
            "activebackground": PALETTE["accent"],
            "activeforeground": "white",
            "bd": 0,
            "relief": "flat",
        }

    def _build_menubar(self) -> None:
        menubar = tk.Menu(self, **self._menu_style())
        file_menu = tk.Menu(menubar, **self._menu_style())
        file_menu.add_command(label="New", command=self.new_config, accelerator="Ctrl+N")
        file_menu.add_separator()
        file_menu.add_command(label="Open Config File (JSON)", command=self.open_config, accelerator="Ctrl+O")
        file_menu.add_command(label="Save Config File (JSON)", command=self.save_config, accelerator="Ctrl+S")
        file_menu.add_command(label="Save As Config File (JSON)", command=self.save_as_config, accelerator="Ctrl+Shift+S")
        menubar.add_cascade(label="File", menu=file_menu)

        import_menu = tk.Menu(menubar, **self._menu_style())
        import_menu.add_command(label="TC File (Excel)", command=self.import_tc_file)
        menubar.add_cascade(label="Import", menu=import_menu)

        export_menu = tk.Menu(menubar, **self._menu_style())
        export_menu.add_command(label="TC File as Excel", command=self.export_tc_file)
        export_menu.add_command(label="TC Result as Excel", command=self.export_result_excel)
        export_menu.add_command(label="TC Result as Pdf", command=self.export_result_pdf)
        menubar.add_cascade(label="Export", menu=export_menu)

        toolbox_menu = tk.Menu(menubar, **self._menu_style())
        toolbox_menu.add_command(label="Copy Cookies from Existing Browser", command=self.copy_cookies_from_browser)
        toolbox_menu.add_command(label="Copy Session from Existing Browser", command=self.copy_session_from_browser)
        menubar.add_cascade(label="Toolbox", menu=toolbox_menu)

        about_menu = tk.Menu(menubar, **self._menu_style())
        about_menu.add_command(label=__about__, command=self.show_about)
        menubar.add_cascade(label="About", menu=about_menu)

        self.configure(menu=menubar)
        self.bind_all("<Control-n>", lambda _e: self.new_config())
        self.bind_all("<Control-o>", lambda _e: self.open_config())
        self.bind_all("<Control-s>", lambda _e: self.save_config())
        self.bind_all("<Control-S>", lambda _e: self.save_as_config())

    def _bind_step_clipboard_keys(self) -> None:
        for widget in (self.steps_tree, self.tab_steps):
            widget.bind("<Control-c>", self._on_step_copy_key)
            widget.bind("<Control-v>", self._on_step_paste_key)

    def _on_step_copy_key(self, event) -> str:
        self.copy_steps()
        return "break"

    def _on_step_paste_key(self, event) -> str:
        self.paste_steps()
        return "break"

    def _sync_step_clipboard_out(self) -> None:
        if not self._step_clipboard:
            return
        payload = json.dumps({"jaqa_steps": [step.to_dict() for step in self._step_clipboard]})
        try:
            self.clipboard_clear()
            self.clipboard_append(payload)
            self.update_idletasks()
        except tk.TclError:
            pass

    def _load_step_clipboard(self) -> bool:
        if self._step_clipboard:
            return True
        try:
            raw = self.clipboard_get()
            data = json.loads(raw)
            items = data.get("jaqa_steps") if isinstance(data, dict) else None
            if items:
                self._step_clipboard = [Step.from_dict(item) for item in items]
        except (tk.TclError, json.JSONDecodeError, TypeError, ValueError):
            pass
        return bool(self._step_clipboard)

    def _step_paste_index(self, case: TestCase) -> int:
        sel = list(self.steps_tree.selection())
        if sel:
            iid = sel[-1]
            for index, step in enumerate(case.steps):
                if step.id == iid:
                    return index + 1
        if self._step_sel:
            for index, step in enumerate(case.steps):
                if step.id == self._step_sel:
                    return index + 1
        return len(case.steps)

    def _update_step_context_menu(self) -> None:
        if not self._step_context_menu:
            return
        can_edit = not self.engine.busy
        has_clipboard = self._load_step_clipboard()
        has_steps = bool(self._target_steps())
        copy_state = "normal" if has_steps and can_edit else "disabled"
        paste_state = "normal" if has_clipboard and can_edit else "disabled"
        enable_state = "normal" if has_steps and can_edit else "disabled"
        delete_state = "normal" if has_steps and can_edit else "disabled"
        self._step_context_menu.entryconfig(0, state=copy_state)
        self._step_context_menu.entryconfig(1, state=paste_state)
        self._step_context_menu.entryconfig(3, state=enable_state)
        self._step_context_menu.entryconfig(4, state=enable_state)
        self._step_context_menu.entryconfig(6, state=delete_state)

    def _build_step_context_menu(self) -> None:
        menu = tk.Menu(self, **self._menu_style())
        menu.add_command(label="Copy", command=self.copy_steps)
        menu.add_command(label="Paste", command=self.paste_steps)
        menu.add_separator()
        menu.add_command(label="Enable", command=lambda: self._set_steps_enabled(True))
        menu.add_command(label="Disable", command=lambda: self._set_steps_enabled(False))
        menu.add_separator()
        menu.add_command(label="Delete", command=self.delete_step)
        self._step_context_menu = menu

    def _bind_exp_clipboard_keys(self) -> None:
        for widget in (self.exp_tree, self.tab_exp):
            widget.bind("<Control-c>", self._on_exp_copy_key)
            widget.bind("<Control-v>", self._on_exp_paste_key)

    def _on_exp_copy_key(self, event) -> str:
        self.copy_expectations()
        return "break"

    def _on_exp_paste_key(self, event) -> str:
        self.paste_expectations()
        return "break"

    def _sync_exp_clipboard_out(self) -> None:
        if not self._exp_clipboard:
            return
        payload = json.dumps({"jaqa_expectations": [item.to_dict() for item in self._exp_clipboard]})
        try:
            self.clipboard_clear()
            self.clipboard_append(payload)
            self.update_idletasks()
        except tk.TclError:
            pass

    def _load_exp_clipboard(self) -> bool:
        if self._exp_clipboard:
            return True
        try:
            raw = self.clipboard_get()
            data = json.loads(raw)
            items = data.get("jaqa_expectations") if isinstance(data, dict) else None
            if items:
                self._exp_clipboard = [Expectation.from_dict(item) for item in items]
        except (tk.TclError, json.JSONDecodeError, TypeError, ValueError):
            pass
        return bool(self._exp_clipboard)

    def _exp_paste_index(self, case: TestCase) -> int:
        sel = list(self.exp_tree.selection())
        if sel:
            iid = sel[-1]
            for index, item in enumerate(case.expectations):
                if item.id == iid:
                    return index + 1
        if self._exp_sel:
            for index, item in enumerate(case.expectations):
                if item.id == self._exp_sel:
                    return index + 1
        return len(case.expectations)

    def _update_exp_context_menu(self) -> None:
        if not self._exp_context_menu:
            return
        can_edit = not self.engine.busy
        has_clipboard = self._load_exp_clipboard()
        has_items = bool(self._target_expectations())
        copy_state = "normal" if has_items and can_edit else "disabled"
        paste_state = "normal" if has_clipboard and can_edit else "disabled"
        enable_state = "normal" if has_items and can_edit else "disabled"
        delete_state = "normal" if has_items and can_edit else "disabled"
        self._exp_context_menu.entryconfig(0, state=copy_state)
        self._exp_context_menu.entryconfig(1, state=paste_state)
        self._exp_context_menu.entryconfig(3, state=enable_state)
        self._exp_context_menu.entryconfig(4, state=enable_state)
        self._exp_context_menu.entryconfig(6, state=delete_state)

    def _build_exp_context_menu(self) -> None:
        menu = tk.Menu(self, **self._menu_style())
        menu.add_command(label="Copy", command=self.copy_expectations)
        menu.add_command(label="Paste", command=self.paste_expectations)
        menu.add_separator()
        menu.add_command(label="Enable", command=lambda: self._set_expectations_enabled(True))
        menu.add_command(label="Disable", command=lambda: self._set_expectations_enabled(False))
        menu.add_separator()
        menu.add_command(label="Delete", command=self.delete_expectation)
        self._exp_context_menu = menu

    def _on_exp_double(self, event) -> str | None:
        if event.widget.identify_column(event.x) == "#1":
            return "break"
        self.edit_expectation()
        return None

    def _on_exp_context_menu(self, event) -> str:
        if not self._exp_context_menu or not self._selected_case():
            return "break"
        tree = self.exp_tree
        if event.widget is tree:
            region = tree.identify_region(event.x, event.y)
            if region in {"heading", "separator"}:
                return "break"
            iid = tree.identify_row(event.y)
        else:
            iid = ""
        if iid:
            current = set(tree.selection())
            if iid not in current:
                tree.selection_set(iid)
            self._exp_sel = iid
        else:
            sel = tree.selection()
            self._exp_sel = sel[-1] if sel else None
        tree.focus_set()
        self._update_exp_context_menu()
        x_root, y_root = int(event.x_root), int(event.y_root)
        self.after(0, lambda: self._show_exp_context_menu(x_root, y_root))
        return "break"

    def _show_exp_context_menu(self, x_root: int, y_root: int) -> None:
        if not self._exp_context_menu:
            return
        try:
            self._exp_context_menu.tk_popup(x_root, y_root)
        finally:
            self._exp_context_menu.grab_release()

    def copy_expectations(self) -> None:
        if not self._can_edit_lists():
            return
        targets = sorted(self._target_expectations(), key=lambda item: item[1])
        if not targets:
            messagebox.showinfo("JAQA", "Pilih expected result yang akan disalin.")
            return
        self._exp_clipboard = [item.duplicate() for _case, _index, item in targets]
        self._sync_exp_clipboard_out()
        label = self._exp_clipboard[0].summary() if len(self._exp_clipboard) == 1 else f"{len(self._exp_clipboard)} expected"
        self._set_status(f"Disalin: {label}")

    def paste_expectations(self) -> None:
        if self.engine.busy:
            messagebox.showinfo("JAQA", "Selesaikan rekaman/run terlebih dahulu.")
            return
        case = self._selected_case()
        if not case:
            messagebox.showinfo("JAQA", "Pilih test case terlebih dahulu.")
            return
        if not self._load_exp_clipboard():
            messagebox.showinfo("JAQA", "Tidak ada expected result di clipboard. Gunakan Copy terlebih dahulu.")
            return
        insert_at = self._exp_paste_index(case)
        clones: list[Expectation] = []
        for i, template in enumerate(self._exp_clipboard):
            clone = template.duplicate()
            if not clone.after_step:
                clone.after_step = len(case.steps)
            case.expectations.insert(insert_at + i, clone)
            clones.append(clone)
        self._exp_sel = clones[-1].id
        self._refresh_table()
        self.exp_tree.selection_set(*[clone.id for clone in clones])
        label = clones[0].summary() if len(clones) == 1 else f"{len(clones)} expected"
        self._set_status(f"Ditempel: {label}")

    def _build_tc_context_menu(self) -> None:
        menu = tk.Menu(self, **self._menu_style())
        menu.add_command(label="Duplicate TC", command=lambda: self.duplicate_case(with_steps=False))
        menu.add_command(label="Duplicate TC + Step", command=lambda: self.duplicate_case(with_steps=True))
        menu.add_separator()
        menu.add_command(label="Enable", command=self.enable_selected)
        menu.add_command(label="Disable", command=self.disable_selected)
        self._tc_context_menu = menu

    def _update_tc_context_menu(self) -> None:
        if not self._tc_context_menu:
            return
        can_edit = not self.engine.busy
        has_cases = bool(self._target_cases())
        state = "normal" if has_cases and can_edit else "disabled"
        self._tc_context_menu.entryconfig(0, state=state)
        self._tc_context_menu.entryconfig(1, state=state)
        self._tc_context_menu.entryconfig(3, state=state)
        self._tc_context_menu.entryconfig(4, state=state)

    def _sync_title(self) -> None:
        name = self.config_path.name if self.config_path else "untitled.json"
        self.title(f"{__full_name__}  •  v{__version__}  —  {name}")

    def _bind_search_refresh(self, search_var: tk.StringVar, callback) -> None:
        search_var.trace_add("write", lambda *_args: callback())

    def _matches_search(self, values: tuple[str, ...], search_var: tk.StringVar) -> bool:
        query = search_var.get().strip()
        if not query:
            return True
        needle = query.lower()
        return any(needle in str(value or "").lower() for value in values)

    def _build_search_box(self, parent: tk.Frame, search_var: tk.StringVar, *, label: str = "Search") -> None:
        tk.Label(
            parent,
            text=label,
            font=("Segoe UI", 9),
            bg=PALETTE["surface"],
            fg=PALETTE["muted"],
        ).pack(side="left", padx=(0, 8))
        tk.Entry(
            parent,
            textvariable=search_var,
            font=("Segoe UI", 9),
            bg=PALETTE["surface_alt"],
            fg=PALETTE["text"],
            insertbackground=PALETTE["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
            highlightcolor=PALETTE["accent"],
        ).pack(side="left", fill="x", expand=True)

    def _make_list_tree(
        self,
        parent,
        columns,
        on_select,
        on_double,
        check_attr: str,
        selectmode: str = "browse",
        on_active_toggle=None,
        search_var: tk.StringVar | None = None,
    ) -> ttk.Treeview:
        data_columns = tuple(columns)
        columns = (("sel", "☐", 40),) + data_columns
        wrap = tk.Frame(parent, bg=PALETTE["surface"])
        wrap.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        if search_var is not None:
            search_row = tk.Frame(wrap, bg=PALETTE["surface"])
            search_row.pack(fill="x", pady=(0, 4))
            self._build_search_box(search_row, search_var)
        tree_host = tk.Frame(wrap, bg=PALETTE["surface"])
        tree_host.pack(fill="both", expand=True)
        tree = ttk.Treeview(tree_host, columns=[c[0] for c in columns], show="headings", selectmode=selectmode)
        bind_tree_style(tree)
        for key, title, width in columns:
            tree.heading(key, text=title)
            tree.column(
                key,
                width=width,
                minwidth=36 if key in {"sel", "aktif"} else 40,
                stretch=key not in {"sel", "aktif"},
                anchor="center" if key in {"sel", "no", "aktif"} else "w",
            )
        tree.heading("sel", command=lambda: self._toggle_list_check_all(tree, check_attr))
        yscroll = ttk.Scrollbar(tree_host, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=yscroll.set)
        tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")
        tree.bind("<<TreeviewSelect>>", lambda _e: on_select())
        tree.bind(
            "<Button-1>",
            lambda event: self._on_list_click(event, tree, check_attr, on_select, on_active_toggle),
            add="+",
        )
        tree.bind("<Double-1>", lambda event: self._on_list_double(event, on_double))
        return tree, wrap

    def _checked_set(self, check_attr: str) -> set[str]:
        return getattr(self, check_attr)

    def _active_icon(self, enabled: bool) -> str:
        return "🟢" if enabled else "⚪"

    def _on_list_click(self, event, tree: ttk.Treeview, check_attr: str, on_select, on_active_toggle=None) -> str | None:
        if tree.identify_region(event.x, event.y) != "cell":
            return None
        column = tree.identify_column(event.x)
        row = tree.identify_row(event.y)
        if not row:
            return None
        if column == "#2" and on_active_toggle:
            on_active_toggle(row)
            return "break"
        if column != "#1":
            return None
        checked = self._checked_set(check_attr)
        if row in checked:
            checked.discard(row)
        else:
            checked.add(row)
        values = list(tree.item(row, "values"))
        if values:
            values[0] = "☑" if row in checked else "☐"
            tree.item(row, values=values)
        if event.state & 0x0005:
            on_select()
            return "break"
        tree.selection_set(row)
        on_select()
        return "break"

    def _on_list_double(self, event, on_double) -> str | None:
        if event.widget.identify_column(event.x) == "#1":
            return "break"
        on_double()
        return None

    def _toggle_list_check_all(self, tree: ttk.Treeview, check_attr: str) -> None:
        ids = list(tree.get_children())
        checked = self._checked_set(check_attr)
        if ids and all(item_id in checked for item_id in ids):
            for item_id in ids:
                checked.discard(item_id)
        else:
            checked.update(ids)
        self._refresh_details()

    def _pack_list_buttons(self, parent, items: tuple) -> None:
        box = ctk.CTkFrame(parent, fg_color="transparent", width=150)
        box.pack(side="right", fill="y", padx=6, pady=6)
        for text, cmd in items:
            ctk.CTkButton(box, text=text, command=cmd, fg_color=PALETTE["surface_alt"], hover_color=PALETTE["border"], width=140, height=28).pack(fill="x", pady=3)

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _selected_case(self) -> TestCase | None:
        if self._selected_id:
            hit = next((tc for tc in self.suite.test_cases if tc.id == self._selected_id), None)
            if hit:
                return hit
        cases = self._selected_cases()
        return cases[0] if cases else None

    def _selected_cases(self) -> list[TestCase]:
        by_id = {tc.id: tc for tc in self.suite.test_cases}
        ids = self._selected_iids()
        return [by_id[iid] for iid in ids if iid in by_id]

    def _selected_iids(self) -> list[str]:
        sel = self.tree.selection()
        if sel:
            return list(sel)
        return [self._selected_id] if self._selected_id else []

    def _selected_iid(self) -> str | None:
        ids = self._selected_iids()
        return ids[-1] if ids else None

    def _on_select(self) -> None:
        sel = self.tree.selection()
        if sel:
            self._selected_id = sel[-1]
        self._refresh_details()

    def _case_values(self, case: TestCase) -> tuple[str, ...]:
        masked = "•" * min(len(case.password), 10) if case.password else ""
        expectation = ""
        if case.expectations:
            expectation = "; ".join(item.summary() for item in case.expectations[:3])
            if len(case.expectations) > 3:
                expectation += f" (+{len(case.expectations) - 3})"
        return (
            "🟢" if case.enabled else "⚪",
            case.no_tc,
            case.deskripsi,
            case.aplikasi,
            case.url,
            case.username,
            masked,
            case.expected_result,
            expectation or "—",
            case.status or "—",
            case.notes,
        )

    def _tag_for(self, case: TestCase, index: int) -> str:
        if not case.enabled:
            return "disabled"
        if case.status == "RUNNING":
            return "run"
        if case.status == "OK":
            return "ok"
        if case.status == "NOK":
            return "nok"
        return "odd" if index % 2 else "even"

    def _on_tree_click(self, event) -> str | None:
        region = self.tree.identify_region(event.x, event.y)
        if region not in {"cell", "tree"}:
            return None
        if self.tree.identify_column(event.x) != "#0":
            return None
        row = self.tree.identify_row(event.y)
        if not row:
            return None
        self._toggle_check(row)
        self.tree.selection_set(row)
        self._selected_id = row
        self._refresh_details()
        return "break"

    def _on_tree_double(self, event) -> str | None:
        if self.tree.identify_column(event.x) == "#0":
            return "break"
        if self._dragging:
            return "break"
        if self.engine.busy or self.recording:
            return "break"
        region = self.tree.identify_region(event.x, event.y)
        if region not in {"cell", "tree"}:
            return None
        row = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not row or not col:
            return None
        key = self._tc_column_key(col)
        if not key:
            return "break"
        if key == "aktif":
            self._toggle_case_enabled(row)
            return "break"
        if key not in TC_EDITABLE:
            return "break"
        self.tree.selection_set(row)
        self._selected_id = row
        self._start_tc_cell_edit(row, col, key)
        return "break"

    def _tc_column_key(self, col_id: str) -> str | None:
        try:
            index = int(col_id.lstrip("#")) - 1
        except ValueError:
            return None
        keys = [key for key, _title, _width in COLUMNS]
        if 0 <= index < len(keys):
            return keys[index]
        return None

    def _toggle_case_enabled(self, case_id: str) -> None:
        case = next((item for item in self.suite.test_cases if item.id == case_id), None)
        if not case:
            return
        case.enabled = not case.enabled
        self._refresh_table()
        state = "ENABLE" if case.enabled else "DISABLE"
        self._set_status(f"{case.no_tc} → {state}")

    def _start_tc_cell_edit(self, row: str, col: str, key: str) -> None:
        self._finish_cell_edit(save=False)
        case = next((item for item in self.suite.test_cases if item.id == row), None)
        if not case:
            return
        bbox = self.tree.bbox(row, col)
        if not bbox:
            return
        x, y, width, height = bbox
        value = getattr(case, key, "")
        entry = tk.Entry(self.tree, borderwidth=0, highlightthickness=1)
        entry.insert(0, str(value or ""))
        entry.select_range(0, "end")
        entry.place(x=x, y=y, width=width, height=height)
        entry.focus_set()
        self._cell_edit = {"entry": entry, "case_id": row, "key": key}
        entry.bind("<Return>", lambda _e: self._finish_cell_edit(save=True))
        entry.bind("<Escape>", lambda _e: self._finish_cell_edit(save=False))
        entry.bind("<FocusOut>", lambda _e: self._finish_cell_edit(save=True))

    def _finish_cell_edit(self, save: bool) -> None:
        if not self._cell_edit:
            return
        info = self._cell_edit
        self._cell_edit = None
        entry = info["entry"]
        new_value = entry.get().strip()
        entry.destroy()
        if not save:
            return
        case = next((item for item in self.suite.test_cases if item.id == info["case_id"]), None)
        if not case:
            return
        key = info["key"]
        if key in {"no_tc", "url"} and not new_value:
            return
        setattr(case, key, new_value)
        self._refresh_table()
        self._set_status(f"{case.no_tc}: {key.replace('_', ' ')} diubah.")

    def _on_tc_drag_start(self, event) -> None:
        if self.engine.busy or self.recording:
            return
        if event.state & 0x0005:
            self._drag_iid = None
            return
        if self.tree.identify_column(event.x) == "#0":
            return
        region = self.tree.identify_region(event.x, event.y)
        if region not in {"cell", "tree"}:
            return
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        self._drag_iid = iid
        self._drag_y = event.y
        self._dragging = False

    def _on_tc_drag_motion(self, event) -> None:
        if not self._drag_iid:
            return
        if abs(event.y - self._drag_y) > 8:
            self._dragging = True

    def _on_tc_drag_drop(self, event) -> None:
        if not self._drag_iid or not self._dragging:
            self._drag_iid = None
            self._dragging = False
            return
        target = self.tree.identify_row(event.y)
        if target and target != self._drag_iid:
            self._reorder_tc(self._drag_iid, target)
        self._drag_iid = None
        self._dragging = False

    def _reorder_tc(self, source_id: str, target_id: str) -> None:
        if self.engine.busy or self.recording:
            return
        src_idx = self.suite.index_of(source_id)
        tgt_idx = self.suite.index_of(target_id)
        if src_idx < 0 or tgt_idx < 0 or src_idx == tgt_idx:
            return
        case = self.suite.test_cases.pop(src_idx)
        self.suite.test_cases.insert(tgt_idx, case)
        self._selected_id = case.id
        self._refresh_table()
        self._set_status(f"Urutan diubah: {case.no_tc} dipindah ke baris {tgt_idx + 1}.")

    def _on_tc_context_menu(self, event) -> str:
        if self.engine.busy or not self._tc_context_menu:
            return "break"
        region = self.tree.identify_region(event.x, event.y)
        if region in {"heading", "separator"}:
            return "break"
        iid = self.tree.identify_row(event.y)
        if not iid:
            return "break"
        current = set(self.tree.selection())
        if iid not in current:
            self.tree.selection_set(iid)
            self._selected_id = iid
        else:
            self._selected_id = iid
        self.tree.focus_set()
        self._update_tc_context_menu()
        x_root, y_root = int(event.x_root), int(event.y_root)
        self.after(0, lambda: self._show_tc_context_menu(x_root, y_root))
        return "break"

    def _show_tc_context_menu(self, x_root: int, y_root: int) -> None:
        if not self._tc_context_menu:
            return
        try:
            self._tc_context_menu.tk_popup(x_root, y_root)
        finally:
            self._tc_context_menu.grab_release()

    def _on_step_double(self, event) -> str | None:
        if event.widget.identify_column(event.x) == "#1":
            return "break"
        if self._step_dragging:
            return "break"
        self.edit_step()
        return None

    def _on_step_drag_start(self, event) -> None:
        if self.engine.busy or self.recording:
            return
        if event.state & 0x0005:
            self._step_drag_iid = None
            return
        if self.steps_tree.identify_column(event.x) == "#1":
            return
        region = self.steps_tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        iid = self.steps_tree.identify_row(event.y)
        if not iid:
            return
        self._step_drag_iid = iid
        self._step_drag_y = event.y
        self._step_dragging = False

    def _on_step_drag_motion(self, event) -> None:
        if not self._step_drag_iid:
            return
        if abs(event.y - self._step_drag_y) > 8:
            self._step_dragging = True

    def _on_step_drag_drop(self, event) -> None:
        if not self._step_drag_iid or not self._step_dragging:
            self._step_drag_iid = None
            self._step_dragging = False
            return
        target = self.steps_tree.identify_row(event.y)
        if target and target != self._step_drag_iid:
            self._reorder_step(self._step_drag_iid, target)
        self._step_drag_iid = None
        self._step_dragging = False

    def _reorder_step(self, source_id: str, target_id: str) -> None:
        if not self._can_edit_lists():
            return
        case = self._selected_case()
        if not case:
            return
        try:
            src_idx = next(i for i, step in enumerate(case.steps) if step.id == source_id)
            tgt_idx = next(i for i, step in enumerate(case.steps) if step.id == target_id)
        except StopIteration:
            return
        if src_idx == tgt_idx:
            return
        step = case.steps.pop(src_idx)
        case.steps.insert(tgt_idx, step)
        self._remap_after_move(case, src_idx, tgt_idx)
        self._step_sel = step.id
        self._refresh_table()
        self._set_status(f"Urutan langkah diubah: {step.summary()} → baris {tgt_idx + 1}.")

    def _on_step_context_menu(self, event) -> str:
        if not self._step_context_menu or not self._selected_case():
            return "break"
        tree = self.steps_tree
        if event.widget is tree:
            region = tree.identify_region(event.x, event.y)
            if region in {"heading", "separator"}:
                return "break"
            iid = tree.identify_row(event.y)
        else:
            iid = ""
        if iid:
            current = set(tree.selection())
            if iid not in current:
                tree.selection_set(iid)
            self._step_sel = iid
        else:
            tree.selection_remove(*tree.selection())
            self._step_sel = None
        tree.focus_set()
        self._update_step_context_menu()
        x_root, y_root = int(event.x_root), int(event.y_root)
        self.after(0, lambda: self._show_step_context_menu(x_root, y_root))
        return "break"

    def _show_step_context_menu(self, x_root: int, y_root: int) -> None:
        if not self._step_context_menu:
            return
        try:
            self._step_context_menu.tk_popup(x_root, y_root)
        finally:
            self._step_context_menu.grab_release()

    def copy_steps(self) -> None:
        if not self._can_edit_lists():
            return
        targets = sorted(self._target_steps(), key=lambda item: item[1])
        if not targets:
            messagebox.showinfo("JAQA", "Pilih langkah yang akan disalin.")
            return
        self._step_clipboard = [step.duplicate() for _case, _index, step in targets]
        self._sync_step_clipboard_out()
        label = self._step_clipboard[0].summary() if len(self._step_clipboard) == 1 else f"{len(self._step_clipboard)} langkah"
        self._set_status(f"Disalin: {label}")

    def paste_steps(self) -> None:
        if self.engine.busy:
            messagebox.showinfo("JAQA", "Selesaikan rekaman/run terlebih dahulu.")
            return
        case = self._selected_case()
        if not case:
            messagebox.showinfo("JAQA", "Pilih test case terlebih dahulu.")
            return
        if not self._load_step_clipboard():
            messagebox.showinfo("JAQA", "Tidak ada langkah di clipboard. Gunakan Copy terlebih dahulu.")
            return
        insert_at = self._step_paste_index(case)
        clones: list[Step] = []
        for i, template in enumerate(self._step_clipboard):
            clone = template.duplicate()
            pos = insert_at + i
            case.steps.insert(pos, clone)
            self._remap_after_insert(case, pos)
            clones.append(clone)
        self._step_sel = clones[-1].id
        self._refresh_table()
        self.steps_tree.selection_set(*[clone.id for clone in clones])
        label = clones[0].summary() if len(clones) == 1 else f"{len(clones)} langkah"
        self._set_status(f"Ditempel: {label}")

    def _toggle_check(self, case_id: str) -> None:
        if case_id in self._checked_ids:
            self._checked_ids.discard(case_id)
        else:
            self._checked_ids.add(case_id)
        if self.tree.exists(case_id):
            case = next((item for item in self.suite.test_cases if item.id == case_id), None)
            if case:
                self.tree.item(
                    case_id,
                    text="",
                    image=self.check_on if case.id in self._checked_ids else self.check_off,
                    values=self._case_values(case),
                )

    def _toggle_check_all(self) -> None:
        ids = [case.id for case in self.suite.test_cases]
        if ids and all(case_id in self._checked_ids for case_id in ids):
            self._checked_ids.clear()
        else:
            self._checked_ids = set(ids)
        self._refresh_table()

    def _target_cases(self) -> list[TestCase]:
        checked = [case for case in self.suite.test_cases if case.id in self._checked_ids]
        if checked:
            return checked
        return self._selected_cases()

    def enable_selected(self) -> None:
        self._set_enabled(True)

    def disable_selected(self) -> None:
        self._set_enabled(False)

    def _set_enabled(self, enabled: bool) -> None:
        if self.engine.busy:
            messagebox.showinfo("JAQA", "Selesaikan rekaman/run terlebih dahulu.")
            return
        cases = self._target_cases()
        if not cases:
            messagebox.showinfo("JAQA", "Centang atau pilih test case terlebih dahulu.")
            return
        for case in cases:
            case.enabled = enabled
        label = "ENABLE" if enabled else "DISABLE"
        self._refresh_table()
        names = ", ".join(case.no_tc for case in cases[:5])
        extra = f" (+{len(cases) - 5})" if len(cases) > 5 else ""
        self._set_status(f"{label}: {names}{extra}")

    def _enabled_only(self, cases: list[TestCase]) -> list[TestCase]:
        return [case for case in cases if case.enabled]

    def _refresh_table(self, keep_selection: bool = True, autosave: bool = True) -> None:
        self._finish_cell_edit(save=False)
        selected = list(self.tree.selection()) if keep_selection else []
        if keep_selection and not selected and self._selected_id:
            selected = [self._selected_id]
        self.tree.delete(*self.tree.get_children())
        for index, case in enumerate(self.suite.test_cases):
            values = self._case_values(case)
            if not self._matches_search(values, self._tc_search):
                continue
            self.tree.insert(
                "",
                "end",
                iid=case.id,
                text="",
                image=self.check_on if case.id in self._checked_ids else self.check_off,
                values=values,
                tags=(self._tag_for(case, index),),
            )
        existing = [iid for iid in selected if self.tree.exists(iid)]
        if existing:
            self.tree.selection_set(*existing)
            self.tree.see(existing[-1])
            self._selected_id = existing[-1]
        elif self.suite.test_cases:
            last = self.suite.test_cases[-1].id
            self.tree.selection_set(last)
            self._selected_id = last
        self._refresh_details()
        if autosave:
            self._autosave()

    def _refresh_details(self) -> None:
        case = self._selected_case()
        step_keep = list(self.steps_tree.selection())
        if not step_keep and self._step_sel:
            step_keep = [self._step_sel]
        exp_keep = list(self.exp_tree.selection())
        if not exp_keep and self._exp_sel:
            exp_keep = [self._exp_sel]
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
            row_values = (
                self._active_icon(step.enabled),
                str(index),
                step.type_label(),
                step.summary(),
                delay,
                step.selector,
                nilai,
            )
            if not self._matches_search(row_values, self._step_search):
                continue
            mark = "☑" if step.id in self._checked_step_ids else "☐"
            self.steps_tree.insert(
                "",
                "end",
                iid=step.id,
                values=(mark, *row_values),
                tags=("odd" if index % 2 else "even",),
            )
        for index, item in enumerate(case.expectations, start=1):
            after = f"Langkah {item.after_step}" if item.after_step else "Akhir"
            row_values = (
                self._active_icon(item.enabled),
                str(index),
                item.label or item.selector,
                item.kind,
                item.match,
                item.expected_value,
                after,
            )
            if not self._matches_search(row_values, self._exp_search):
                continue
            mark = "☑" if item.id in self._checked_exp_ids else "☐"
            self.exp_tree.insert(
                "",
                "end",
                iid=item.id,
                values=(mark, *row_values),
                tags=("odd" if index % 2 else "even",),
            )
        if step_keep:
            existing_steps = [iid for iid in step_keep if self.steps_tree.exists(iid)]
            if existing_steps:
                self.steps_tree.selection_set(*existing_steps)
                self.steps_tree.see(existing_steps[-1])
                self._step_sel = existing_steps[-1]
        if exp_keep:
            existing_exp = [iid for iid in exp_keep if self.exp_tree.exists(iid)]
            if existing_exp:
                self.exp_tree.selection_set(*existing_exp)
                self.exp_tree.see(existing_exp[-1])
                self._exp_sel = existing_exp[-1]
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
        self._checked_ids.discard(case.id)
        self._selected_id = None
        self._refresh_table(keep_selection=False)
        self._set_status(f"{case.no_tc} dihapus.")

    def duplicate_case(self, with_steps: bool = False) -> None:
        if self.engine.busy or self.recording:
            messagebox.showinfo("JAQA", "Selesaikan rekaman/run terlebih dahulu.")
            return
        cases = self._selected_cases()
        if not cases:
            messagebox.showinfo("JAQA", "Pilih test case yang akan diduplikasi.")
            return
        clones: list[TestCase] = []
        for case in reversed(cases):
            clone = case.duplicate(with_steps=with_steps)
            idx = self.suite.index_of(case.id)
            self.suite.test_cases.insert(idx + 1, clone)
            clones.append(clone)
        clones.reverse()
        self._selected_id = clones[-1].id
        self._refresh_table()
        clone_ids = [clone.id for clone in clones]
        self.tree.selection_set(*clone_ids)
        label = "Duplicate TC + Step" if with_steps else "Duplicate TC"
        if len(clones) == 1:
            extra = f" ({len(clones[0].steps)} langkah, {len(clones[0].expectations)} expected)" if with_steps else ""
            self._set_status(f"{label}: {clones[0].no_tc}{extra}")
        else:
            self._set_status(f"{label}: {len(clones)} test case diduplikasi.")

    def _toggle_step_enabled(self, step_id: str) -> None:
        if self.engine.busy:
            return
        case = self._selected_case()
        if not case:
            return
        step = next((item for item in case.steps if item.id == step_id), None)
        if not step:
            return
        step.enabled = not step.enabled
        self._refresh_details()
        state = "ENABLE" if step.enabled else "DISABLE"
        self._set_status(f"{state} step: {step.summary()}")

    def _toggle_expectation_enabled(self, exp_id: str) -> None:
        if self.engine.busy:
            return
        case = self._selected_case()
        if not case:
            return
        item = next((entry for entry in case.expectations if entry.id == exp_id), None)
        if not item:
            return
        item.enabled = not item.enabled
        self._refresh_details()
        state = "ENABLE" if item.enabled else "DISABLE"
        self._set_status(f"{state} expected: {item.summary()}")

    def _set_steps_enabled(self, enabled: bool) -> None:
        if not self._can_edit_lists():
            return
        targets = self._target_steps()
        if not targets:
            messagebox.showinfo("JAQA", "Select or check steps first.")
            return
        for _case, _index, step in targets:
            step.enabled = enabled
        label = "ENABLE" if enabled else "DISABLE"
        self._refresh_details()
        self._set_status(f"{label}: {len(targets)} step(s)")

    def _set_expectations_enabled(self, enabled: bool) -> None:
        if not self._can_edit_lists():
            return
        targets = self._target_expectations()
        if not targets:
            messagebox.showinfo("JAQA", "Select or check expected results first.")
            return
        for _case, _index, item in targets:
            item.enabled = enabled
        label = "ENABLE" if enabled else "DISABLE"
        self._refresh_details()
        self._set_status(f"{label}: {len(targets)} expected result(s)")

    def _can_edit_lists(self) -> bool:
        if self.engine.busy:
            messagebox.showinfo("JAQA", "Selesaikan rekaman/run terlebih dahulu.")
            return False
        return self._require_case() is not None

    def _on_step_select(self) -> None:
        sel = self.steps_tree.selection()
        if sel:
            self._step_sel = sel[-1]

    def _on_exp_select(self) -> None:
        sel = self.exp_tree.selection()
        if sel:
            self._exp_sel = sel[-1]

    def _selected_step(self) -> tuple[TestCase, int, Step] | None:
        targets = self._target_steps()
        return targets[0] if targets else None

    def _selected_expectation(self) -> tuple[TestCase, int, Expectation] | None:
        targets = self._target_expectations()
        return targets[0] if targets else None

    def _target_steps(self) -> list[tuple[TestCase, int, Step]]:
        case = self._selected_case()
        if not case:
            return []
        sel = list(self.steps_tree.selection())
        if not sel and self._step_sel:
            sel = [self._step_sel]
        if sel:
            by_id = {step.id: (index, step) for index, step in enumerate(case.steps)}
            result: list[tuple[TestCase, int, Step]] = []
            for iid in sel:
                hit = by_id.get(iid)
                if hit:
                    result.append((case, hit[0], hit[1]))
            if result:
                return result
        return [(case, index, step) for index, step in enumerate(case.steps) if step.id in self._checked_step_ids]

    def _target_expectations(self) -> list[tuple[TestCase, int, Expectation]]:
        case = self._selected_case()
        if not case:
            return []
        sel = list(self.exp_tree.selection())
        if not sel and self._exp_sel:
            sel = [self._exp_sel]
        if sel:
            by_id = {item.id: (index, item) for index, item in enumerate(case.expectations)}
            result: list[tuple[TestCase, int, Expectation]] = []
            for iid in sel:
                hit = by_id.get(iid)
                if hit:
                    result.append((case, hit[0], hit[1]))
            if result:
                return result
        return [(case, index, item) for index, item in enumerate(case.expectations) if item.id in self._checked_exp_ids]

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
        targets = self._target_steps()
        if not targets:
            messagebox.showinfo("JAQA", "Centang atau pilih langkah yang akan dihapus.")
            return
        label = targets[0][2].summary() if len(targets) == 1 else f"{len(targets)} langkah terpilih"
        if not ask_yes_no(self, "Delete Step", f"Hapus {label}?"):
            return
        case = targets[0][0]
        for _case, index, step in sorted(targets, key=lambda item: item[1], reverse=True):
            case.steps.pop(index)
            self._remap_after_delete(case, index)
            self._checked_step_ids.discard(step.id)
        self._step_sel = case.steps[min(targets[0][1], len(case.steps) - 1)].id if case.steps else None
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
        targets = self._target_expectations()
        if not targets:
            messagebox.showinfo("JAQA", "Centang atau pilih expected result yang akan dihapus.")
            return
        label = targets[0][2].summary() if len(targets) == 1 else f"{len(targets)} expected terpilih"
        if not ask_yes_no(self, "Delete Expected", f"Hapus {label}?"):
            return
        case = targets[0][0]
        for _case, index, item in sorted(targets, key=lambda row: row[1], reverse=True):
            case.expectations.pop(index)
            self._checked_exp_ids.discard(item.id)
        self._exp_sel = case.expectations[min(targets[0][1], len(case.expectations) - 1)].id if case.expectations else None
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
        self._set_status(f"Merekam {case.no_tc}. Lakukan langkah di browser. Klik EXPECTED RESULT untuk menandai hasil.")

    def toggle_expect(self) -> None:
        if not self.recording:
            messagebox.showinfo("JAQA", "EXPECTED RESULT hanya tersedia saat RECORD berlangsung.")
            return
        self._apply_expect_mode(not self.expect_armed)

    def _apply_expect_mode(self, enabled: bool, sync_browser: bool = True) -> None:
        self.expect_armed = bool(enabled)
        if sync_browser:
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
        runnable = self._enabled_only(cases)
        skipped = len(cases) - len(runnable)
        if not runnable:
            messagebox.showinfo("JAQA", "Tidak ada test case ENABLE yang bisa dijalankan.")
            return
        for case in runnable:
            case.status = "RUNNING"
            case.notes = "Sedang dijalankan..."
            case.expectation_results = []
        self._refresh_table()
        try:
            self.engine.run_cases(runnable)
        except RuntimeError as exc:
            messagebox.showerror("JAQA", str(exc))
            return
        extra = f"  •  {skipped} DISABLE dilewati" if skipped else ""
        self._set_status(f"Menjalankan {len(runnable)} test case ENABLE...{extra}")

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

    def _busy_blocked(self) -> bool:
        if self.engine.busy:
            messagebox.showinfo("JAQA", "Selesaikan rekaman/run terlebih dahulu.")
            return True
        return False

    def _ask_browser_import(self, title: str) -> BrowserImportSource | None:
        dialog = BrowserImportDialog(self, title=title)
        self.wait_window(dialog)
        return dialog.result

    def copy_cookies_from_browser(self) -> None:
        if self._busy_blocked():
            return
        case = self._require_case()
        if not case:
            return
        source = self._ask_browser_import("Copy Cookies from Existing Browser")
        if not source:
            return
        self._set_status("Menyalin cookies dari browser...")
        threading.Thread(
            target=self._copy_cookies_worker,
            args=(case.id, source),
            daemon=True,
            name="jaqa-copy-cookies",
        ).start()

    def copy_session_from_browser(self) -> None:
        if self._busy_blocked():
            return
        case = self._require_case()
        if not case:
            return
        source = self._ask_browser_import("Copy Session from Existing Browser")
        if not source:
            return
        self._set_status("Menyalin session dari browser...")
        threading.Thread(
            target=self._copy_session_worker,
            args=(case.id, source),
            daemon=True,
            name="jaqa-copy-session",
        ).start()

    def _copy_cookies_worker(self, case_id: str, source: BrowserImportSource) -> None:
        try:
            cookies, warnings = fetch_cookies(source)
            self.events.put(
                ("cookies_copied", {"case_id": case_id, "cookies": cookies, "count": len(cookies), "warnings": warnings})
            )
        except Exception as exc:
            self.events.put(("error", {"message": f"Gagal menyalin cookies:\n{exc}"}))

    def _copy_session_worker(self, case_id: str, source: BrowserImportSource) -> None:
        try:
            storage_state, warnings = fetch_storage_state(source)
            cookies = storage_state.get("cookies") or []
            self.events.put(
                (
                    "session_copied",
                    {
                        "case_id": case_id,
                        "storage_state": storage_state,
                        "cookies": cookies,
                        "count": len(cookies),
                        "origins": len(storage_state.get("origins") or []),
                        "warnings": warnings,
                    },
                )
            )
        except Exception as exc:
            self.events.put(("error", {"message": f"Gagal menyalin session:\n{exc}"}))

    def _initial_dir(self) -> str:
        if self.config_path:
            return str(self.config_path.parent)
        last = last_config_path()
        return str(last.parent) if last else str(Path.home())

    def new_config(self) -> None:
        if self._busy_blocked():
            return
        if self.suite.test_cases and not ask_yes_no(self, "New Config", "Buat config baru? Perubahan yang belum disimpan akan hilang."):
            return
        self.suite = TestSuite()
        self.config_path = None
        self._selected_id = None
        self._checked_ids.clear()
        self._refresh_table(keep_selection=False)
        self._sync_title()
        self._set_status("Config baru. Tambah test case atau simpan sebagai file JSON.")

    def open_config(self) -> None:
        if self._busy_blocked():
            return
        path = filedialog.askopenfilename(
            title="Open Config File (JSON)",
            filetypes=[("JSON", "*.json"), ("Semua", "*.*")],
            initialdir=self._initial_dir(),
        )
        if not path:
            return
        try:
            opened = import_json(path)
        except Exception as exc:
            messagebox.showerror("JAQA", f"Gagal membuka config JSON:\n{exc}")
            return
        if self.suite.test_cases and not ask_yes_no(self, "Open Config", "Ganti suite saat ini dengan isi file JSON?"):
            return
        self.suite = opened
        self.config_path = Path(path)
        remember_config_path(self.config_path)
        self._selected_id = None
        self._refresh_table(keep_selection=False)
        self._sync_title()
        self._set_status(f"Config dibuka: {self.config_path.name}  ({len(self.suite.test_cases)} TC)")

    def save_config(self) -> None:
        if self.config_path:
            try:
                export_json(self.suite, self.config_path)
            except Exception as exc:
                messagebox.showerror("JAQA", f"Gagal menyimpan config:\n{exc}")
                return
            remember_config_path(self.config_path)
            self._autosave()
            self._set_status(f"Config disimpan: {self.config_path}")
            return
        self.save_as_config()

    def save_as_config(self) -> None:
        initial = self.config_path.name if self.config_path else "jaqa_config.json"
        path = filedialog.asksaveasfilename(
            title="Save As Config File (JSON)",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialdir=self._initial_dir(),
            initialfile=initial,
        )
        if not path:
            return
        try:
            export_json(self.suite, path)
        except Exception as exc:
            messagebox.showerror("JAQA", f"Gagal menyimpan config:\n{exc}")
            return
        self.config_path = Path(path)
        remember_config_path(self.config_path)
        self._autosave()
        self._sync_title()
        self._set_status(f"Config disimpan: {self.config_path}")

    def import_tc_file(self) -> None:
        if self._busy_blocked():
            return
        path = filedialog.askopenfilename(
            title="Import TC File (Excel)",
            filetypes=[("Excel", "*.xlsx *.xlsm *.xls"), ("Semua", "*.*")],
            initialdir=self._initial_dir(),
        )
        if not path:
            return
        try:
            imported = import_tc_excel(path)
        except Exception as exc:
            messagebox.showerror("JAQA", f"Gagal impor TC Excel:\n{exc}")
            return
        if not imported.test_cases:
            messagebox.showwarning("JAQA", "Tidak ada test case yang bisa dibaca dari file Excel.")
            return
        if self.suite.test_cases:
            replace = ask_yes_no(
                self,
                "Import TC File",
                f"Suite saat ini berisi {len(self.suite.test_cases)} TC.\n\nYa = ganti semua.\nTidak = tambahkan TC dari Excel.",
            )
            if replace:
                self.suite = imported
            else:
                self.suite.test_cases.extend(imported.test_cases)
        else:
            self.suite = imported
        self._selected_id = None
        self._refresh_table(keep_selection=False)
        self._set_status(f"TC diimpor dari {Path(path).name}: {len(imported.test_cases)} baris")

    def export_tc_file(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Export TC File as Excel",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialdir=str(reports_dir()),
            initialfile="JAQA_TC.xlsx",
        )
        if not path:
            return
        export_tc_excel(self.suite, path)
        self._set_status(f"TC File Excel tersimpan: {path}")

    def export_result_excel(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Export TC Result as Excel",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialdir=str(reports_dir()),
            initialfile="JAQA_Laporan_SIT.xlsx",
        )
        if not path:
            return
        export_excel(self.suite, path)
        self._set_status(f"Hasil Excel tersimpan: {path}")

    def export_result_pdf(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Export TC Result as Pdf",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            initialdir=str(reports_dir()),
            initialfile="JAQA_Laporan_SIT.pdf",
        )
        if not path:
            return
        export_pdf(self.suite, path)
        self._set_status(f"Hasil PDF tersimpan: {path}")

    def show_about(self) -> None:
        dialog = AboutDialog(self)
        self.wait_window(dialog)

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
        elif kind == "expect_mode_changed":
            self._apply_expect_mode(bool(payload.get("enabled")), sync_browser=False)
        elif kind == "record_stop_requested":
            self._set_status("Menghentikan rekaman...")
        elif kind == "cookies_copied":
            case = next((item for item in self.suite.test_cases if item.id == payload.get("case_id")), None)
            if not case:
                return
            case.browser_cookies = payload.get("cookies") or []
            case.browser_storage_state = {}
            self._autosave()
            extra = warnings_text(payload.get("warnings") or [])
            self._set_status(f"{case.no_tc}: {payload.get('count', 0)} cookies disalin ke test case.{extra}")
        elif kind == "session_copied":
            case = next((item for item in self.suite.test_cases if item.id == payload.get("case_id")), None)
            if not case:
                return
            case.browser_storage_state = payload.get("storage_state") or {}
            case.browser_cookies = payload.get("cookies") or []
            self._autosave()
            origins = payload.get("origins", 0)
            extra = warnings_text(payload.get("warnings") or [])
            self._set_status(
                f"{case.no_tc}: session disalin ({payload.get('count', 0)} cookies, {origins} origin localStorage).{extra}"
            )
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
        self.lift()
        self.focus_force()
        dialog = ExpectationDialog(self, preview, step_count=len(case.steps), topmost=True)
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
