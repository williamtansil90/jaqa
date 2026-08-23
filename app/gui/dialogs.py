from __future__ import annotations

from tkinter import ttk

import customtkinter as ctk

from app.core.models import STEP_TYPE_LABELS, Expectation, Step, TestCase
from app.gui.theme import PALETTE


class _FormDialog(ctk.CTkToplevel):
    def __init__(self, master, title: str, width: int = 620, height: int = 560) -> None:
        super().__init__(master)
        self.title(title)
        self.geometry(f"{width}x{height}")
        self.minsize(width, height)
        self.configure(fg_color=PALETTE["bg"])
        self.transient(master)
        self.grab_set()
        self.result = None
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _e: self._cancel())

    def _cancel(self) -> None:
        self.result = None
        self.destroy()

    def _field(self, parent, label: str, widget: ctk.CTkBaseClass, required: bool = False) -> None:
        text = f"{label} *" if required else label
        ctk.CTkLabel(parent, text=text, text_color=PALETTE["muted"], anchor="w").pack(fill="x", pady=(8, 2))
        widget.pack(fill="x")


class TestCaseDialog(_FormDialog):
    def __init__(self, master, case: TestCase | None = None) -> None:
        super().__init__(master, "Ubah Test Case" if case else "Tambah Test Case", 640, 620)
        self.case = case
        wrap = ctk.CTkScrollableFrame(self, fg_color=PALETTE["surface"], corner_radius=12)
        wrap.pack(fill="both", expand=True, padx=16, pady=16)

        self.no_tc = ctk.CTkEntry(wrap, placeholder_text="TC-001")
        self.deskripsi = ctk.CTkTextbox(wrap, height=72)
        self.aplikasi = ctk.CTkEntry(wrap, placeholder_text="Nama aplikasi")
        self.url = ctk.CTkEntry(wrap, placeholder_text="https://...")
        self.username = ctk.CTkEntry(wrap)
        self.password = ctk.CTkEntry(wrap, show="•")
        self.expected = ctk.CTkTextbox(wrap, height=80)

        self._field(wrap, "NO. TC", self.no_tc, True)
        self._field(wrap, "Deskripsi", self.deskripsi)
        self._field(wrap, "Aplikasi", self.aplikasi)
        self._field(wrap, "URL", self.url, True)
        self._field(wrap, "Username", self.username)
        self._field(wrap, "Password", self.password)
        self._field(wrap, "Expected Result (keterangan)", self.expected)

        if case:
            self.no_tc.insert(0, case.no_tc)
            self.deskripsi.insert("1.0", case.deskripsi)
            self.aplikasi.insert(0, case.aplikasi)
            self.url.insert(0, case.url)
            self.username.insert(0, case.username)
            self.password.insert(0, case.password)
            self.expected.insert("1.0", case.expected_result)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=16, pady=(0, 16))
        ctk.CTkButton(actions, text="Batal", fg_color=PALETTE["surface_alt"], hover_color=PALETTE["border"], command=self._cancel).pack(side="right", padx=(8, 0))
        ctk.CTkButton(actions, text="Simpan", fg_color=PALETTE["accent"], hover_color=PALETTE["accent_hover"], command=self._save).pack(side="right")
        self.after(80, self.no_tc.focus_set)

    def _save(self) -> None:
        no_tc = self.no_tc.get().strip()
        url = self.url.get().strip()
        if not no_tc:
            self.no_tc.focus_set()
            return
        if not url:
            self.url.focus_set()
            return
        case = self.case or TestCase()
        case.no_tc = no_tc
        case.deskripsi = self.deskripsi.get("1.0", "end").strip()
        case.aplikasi = self.aplikasi.get().strip()
        case.url = url
        case.username = self.username.get().strip()
        case.password = self.password.get()
        case.expected_result = self.expected.get("1.0", "end").strip()
        self.result = case
        self.destroy()


class StepDialog(_FormDialog):
    def __init__(self, master, step: Step | None = None, delay_only: bool = False) -> None:
        title = "Tambah Delay" if delay_only else ("Ubah Langkah" if step else "Tambah Langkah")
        super().__init__(master, title, 560, 520 if not delay_only else 280)
        self.existing = step
        wrap = ctk.CTkFrame(self, fg_color=PALETTE["surface"], corner_radius=12)
        wrap.pack(fill="both", expand=True, padx=16, pady=16)

        type_values = list(STEP_TYPE_LABELS.values())
        self._type_map = {label: key for key, label in STEP_TYPE_LABELS.items()}
        self.step_type = ctk.CTkOptionMenu(wrap, values=type_values)
        start_type = "wait" if delay_only else (step.type if step else "click")
        self.step_type.set(STEP_TYPE_LABELS.get(start_type, "Klik"))
        if delay_only:
            self.step_type.configure(state="disabled")
        else:
            self._field(wrap, "Jenis langkah", self.step_type)

        self.label = ctk.CTkEntry(wrap, placeholder_text="Keterangan langkah")
        self.selector = ctk.CTkEntry(wrap, placeholder_text="#id atau selector CSS")
        self.value = ctk.CTkEntry(wrap, placeholder_text="Nilai / teks / ms untuk delay")
        self.url = ctk.CTkEntry(wrap, placeholder_text="https://...")
        self.key = ctk.CTkEntry(wrap, placeholder_text="Enter")
        self.delay = ctk.CTkEntry(wrap, placeholder_text="jeda setelah langkah (ms)")
        self.checked = ctk.CTkOptionMenu(wrap, values=["Tidak berubah", "Centang", "Hapus centang"])

        if not delay_only:
            self._field(wrap, "Label", self.label)
            self._field(wrap, "Selector", self.selector)
            self._field(wrap, "Nilai / teks", self.value)
            self._field(wrap, "URL (untuk buka halaman)", self.url)
            self._field(wrap, "Tombol (untuk press)", self.key)
            self._field(wrap, "Checkbox", self.checked)
            self._field(wrap, "Jeda setelah langkah (ms)", self.delay)
        else:
            self._field(wrap, "Delay / tunggu (ms)", self.value, True)
            ctk.CTkLabel(
                wrap,
                text="Contoh: 2000 = tunggu 2 detik sebelum langkah berikutnya.",
                text_color=PALETTE["muted"],
                anchor="w",
            ).pack(fill="x", pady=(8, 0))

        if step:
            self.label.insert(0, step.label)
            self.selector.insert(0, step.selector)
            self.value.insert(0, step.value)
            self.url.insert(0, step.url)
            self.key.insert(0, step.key)
            self.delay.insert(0, str(step.delay_ms or 0))
            if step.checked is True:
                self.checked.set("Centang")
            elif step.checked is False:
                self.checked.set("Hapus centang")
        elif delay_only:
            self.value.insert(0, "2000")

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=16, pady=(0, 16))
        ctk.CTkButton(actions, text="Batal", fg_color=PALETTE["surface_alt"], hover_color=PALETTE["border"], command=self._cancel).pack(side="right", padx=(8, 0))
        ctk.CTkButton(actions, text="Simpan", fg_color=PALETTE["accent"], hover_color=PALETTE["accent_hover"], command=self._save).pack(side="right")
        self.after(80, (self.value if delay_only else self.label).focus_set)

    def _save(self) -> None:
        step_type = self._type_map.get(self.step_type.get(), "click")
        value = self.value.get().strip()
        if step_type == "wait":
            if not value.isdigit() or int(value) < 0:
                self.value.focus_set()
                return
        delay_raw = self.delay.get().strip() or "0"
        if not delay_raw.isdigit():
            self.delay.focus_set()
            return
        checked = None
        if self.checked.get() == "Centang":
            checked = True
        elif self.checked.get() == "Hapus centang":
            checked = False
        step = self.existing or Step(type=step_type)
        step.type = step_type
        step.label = self.label.get().strip()
        step.selector = self.selector.get().strip()
        step.value = value
        step.url = self.url.get().strip()
        step.key = self.key.get().strip()
        step.delay_ms = int(delay_raw)
        step.checked = checked
        if step_type == "wait" and not step.label:
            step.label = f"Delay {value} ms"
        self.result = step
        self.destroy()


class ExpectationDialog(_FormDialog):
    def __init__(self, master, preview: dict, existing: Expectation | None = None, step_count: int = 0) -> None:
        super().__init__(master, "Ubah Expected Result" if existing else "Tambah Expected Result", 560, 620)
        self.existing = existing
        wrap = ctk.CTkScrollableFrame(self, fg_color=PALETTE["surface"], corner_radius=12)
        wrap.pack(fill="both", expand=True, padx=16, pady=16)

        selector = preview.get("selector") or (existing.selector if existing else "")
        sample = preview.get("sample_text") or (existing.sample_text if existing else "")
        default_label = preview.get("label") or (existing.label if existing else "")
        input_like = bool(preview.get("input_like"))

        ctk.CTkLabel(wrap, text="Selector elemen", text_color=PALETTE["muted"], anchor="w").pack(fill="x", pady=(4, 2))
        sel = ctk.CTkEntry(wrap)
        sel.insert(0, selector)
        sel.pack(fill="x")
        self.selector = sel

        hint = sample or preview.get("value") or ""
        if hint:
            ctk.CTkLabel(wrap, text=f"Cuplikan: {hint}", text_color=PALETTE["gold"], anchor="w", wraplength=500).pack(fill="x", pady=(6, 0))

        self.label = ctk.CTkEntry(wrap, placeholder_text="Nama expected")
        self._field(wrap, "Label", self.label)
        if default_label:
            self.label.insert(0, default_label)

        kinds = ["text", "value", "visible", "attribute", "checked"]
        kind_labels = {
            "text": "Teks tampilan",
            "value": "Nilai input",
            "visible": "Elemen terlihat",
            "attribute": "Atribut HTML",
            "checked": "Checkbox/radio",
        }
        self.kind = ctk.CTkOptionMenu(wrap, values=[kind_labels[k] for k in kinds])
        self._kind_map = {kind_labels[k]: k for k in kinds}
        self._rev_kind = {v: k for k, v in self._kind_map.items()}
        start_kind = existing.kind if existing else ("value" if input_like else "text")
        self.kind.set(self._rev_kind.get(start_kind, "Teks tampilan"))
        self._field(wrap, "Jenis pemeriksaan", self.kind)

        self.attribute = ctk.CTkEntry(wrap, placeholder_text="contoh: href, class, src")
        self._field(wrap, "Nama atribut (jika jenis = atribut)", self.attribute)
        if existing and existing.attribute:
            self.attribute.insert(0, existing.attribute)

        match_labels = {"equals": "Sama dengan", "contains": "Mengandung", "regex": "Regex"}
        self.match = ctk.CTkOptionMenu(wrap, values=list(match_labels.values()))
        self._match_map = {v: k for k, v in match_labels.items()}
        start_match = existing.match if existing else "contains"
        self.match.set(next(k for k, v in self._match_map.items() if v == start_match))
        self._field(wrap, "Cara membandingkan", self.match)

        self.expected = ctk.CTkEntry(wrap, placeholder_text="Nilai yang diharapkan")
        self._field(wrap, "Nilai expected", self.expected, True)
        preset = existing.expected_value if existing else (preview.get("value") or sample or "")
        if preset:
            self.expected.insert(0, preset)

        after_values = ["Di akhir test case"] + [f"Setelah langkah {i}" for i in range(1, max(step_count, 1) + 1)]
        self.after_step = ctk.CTkOptionMenu(wrap, values=after_values)
        current_after = existing.after_step if existing else int(preview.get("after_step") or step_count or 0)
        if current_after and current_after <= max(step_count, 1):
            self.after_step.set(f"Setelah langkah {current_after}")
        else:
            self.after_step.set("Di akhir test case")
        self._field(wrap, "Periksa kapan", self.after_step)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=16, pady=(0, 16))
        ctk.CTkButton(actions, text="Batal", fg_color=PALETTE["surface_alt"], hover_color=PALETTE["border"], command=self._cancel).pack(side="right", padx=(8, 0))
        ctk.CTkButton(actions, text="Simpan Expected", fg_color=PALETTE["accent"], hover_color=PALETTE["accent_hover"], command=self._save).pack(side="right")
        self.after(80, self.expected.focus_set)

    def _save(self) -> None:
        kind = self._kind_map[self.kind.get()]
        value = self.expected.get().strip()
        if kind not in {"visible"} and not value:
            self.expected.focus_set()
            return
        after_text = self.after_step.get()
        after_step = 0
        if after_text.startswith("Setelah langkah"):
            after_step = int(after_text.rsplit(" ", 1)[-1])
        result = self.existing or Expectation()
        result.selector = self.selector.get().strip()
        result.kind = kind  # type: ignore[arg-type]
        result.attribute = self.attribute.get().strip()
        result.match = self._match_map[self.match.get()]  # type: ignore[arg-type]
        result.expected_value = value
        result.label = self.label.get().strip()
        result.after_step = after_step
        if not result.sample_text:
            result.sample_text = value
        self.result = result
        self.destroy()


def ask_yes_no(master, title: str, message: str) -> bool:
    dialog = ctk.CTkToplevel(master)
    dialog.title(title)
    dialog.geometry("420x180")
    dialog.configure(fg_color=PALETTE["bg"])
    dialog.transient(master)
    dialog.grab_set()
    result = {"ok": False}
    ctk.CTkLabel(dialog, text=message, wraplength=360, justify="left").pack(padx=20, pady=24, fill="x")
    bar = ctk.CTkFrame(dialog, fg_color="transparent")
    bar.pack(fill="x", padx=20, pady=12)

    def yes() -> None:
        result["ok"] = True
        dialog.destroy()

    ctk.CTkButton(bar, text="Batal", fg_color=PALETTE["surface_alt"], command=dialog.destroy).pack(side="right", padx=(8, 0))
    ctk.CTkButton(bar, text="Ya", fg_color=PALETTE["accent"], command=yes).pack(side="right")
    dialog.wait_window()
    return result["ok"]


def bind_tree_style(tree: ttk.Treeview) -> None:
    style = ttk.Style(tree)
    style.theme_use("clam")
    style.configure(
        "JAQA.Treeview",
        background=PALETTE["surface"],
        fieldbackground=PALETTE["surface"],
        foreground=PALETTE["text"],
        rowheight=30,
        borderwidth=0,
        font=("Segoe UI", 10),
    )
    style.configure(
        "JAQA.Treeview.Heading",
        background=PALETTE["surface_alt"],
        foreground=PALETTE["text"],
        relief="flat",
        font=("Segoe UI Semibold", 9),
        padding=6,
    )
    style.map("JAQA.Treeview", background=[("selected", PALETTE["accent"])], foreground=[("selected", "white")])
    style.map("JAQA.Treeview.Heading", background=[("active", PALETTE["accent"])])
    tree.configure(style="JAQA.Treeview")
    tree.tag_configure("ok", background="#14532D", foreground="#DCFCE7")
    tree.tag_configure("nok", background="#7F1D1D", foreground="#FEE2E2")
    tree.tag_configure("run", background="#1E3A5F", foreground="#DBEAFE")
    tree.tag_configure("odd", background="#152033")
    tree.tag_configure("even", background=PALETTE["surface"])
