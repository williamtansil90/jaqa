from __future__ import annotations

import customtkinter as ctk

PALETTE = {
    "bg": "#0B1220",
    "surface": "#121B2E",
    "surface_alt": "#18233A",
    "border": "#24324D",
    "accent": "#0F766E",
    "accent_hover": "#0D9488",
    "gold": "#D4A017",
    "text": "#E8EEF4",
    "muted": "#94A3B8",
    "ok": "#16A34A",
    "nok": "#DC2626",
    "warn": "#C2410C",
    "row_ok": "#14532D",
    "row_nok": "#7F1D1D",
    "row_run": "#1E3A5F",
}


def apply_theme() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
