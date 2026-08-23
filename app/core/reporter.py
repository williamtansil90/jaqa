from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.models import TestSuite

HEADERS = [
    "NO. TC",
    "Deskripsi",
    "Aplikasi",
    "URL",
    "Username",
    "Password",
    "Expected Result",
    "Status",
    "Catatan",
]


def _rows(suite: TestSuite) -> list[list[str]]:
    rows: list[list[str]] = []
    for case in suite.test_cases:
        expected = case.expected_result
        extra = []
        for item in case.expectations:
            extra.append(item.summary())
        if extra:
            expected = (expected + "\n" if expected else "") + "\n".join(f"• {text}" for text in extra)
        rows.append(
            [
                case.no_tc,
                case.deskripsi,
                case.aplikasi,
                case.url,
                case.username,
                case.password,
                expected,
                case.status or "BELUM DIUJI",
                case.notes,
            ]
        )
    return rows


def export_excel(suite: TestSuite, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    sheet = book.active
    sheet.title = "Hasil SIT"

    title_fill = PatternFill("solid", fgColor="0B3A4A")
    header_fill = PatternFill("solid", fgColor="115E67")
    ok_fill = PatternFill("solid", fgColor="C6F4D6")
    nok_fill = PatternFill("solid", fgColor="FECACA")
    pending_fill = PatternFill("solid", fgColor="E5E7EB")
    alt_fill = PatternFill("solid", fgColor="F0FDFA")
    thin = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1"),
    )
    white = Font(color="FFFFFF", bold=True, name="Calibri")
    wrap = Alignment(wrap_text=True, vertical="center")

    sheet.merge_cells("A1:I1")
    sheet["A1"] = "JAQA — Jalin Automate QA  |  Laporan Hasil SIT"
    sheet["A1"].font = Font(color="FFFFFF", bold=True, size=16, name="Calibri")
    sheet["A1"].fill = title_fill
    sheet["A1"].alignment = Alignment(horizontal="left", vertical="center", indent=1)
    sheet.row_dimensions[1].height = 28

    sheet.merge_cells("A2:I2")
    ok_n = sum(1 for tc in suite.test_cases if tc.status == "OK")
    nok_n = sum(1 for tc in suite.test_cases if tc.status == "NOK")
    pending_n = len(suite.test_cases) - ok_n - nok_n
    sheet["A2"] = (
        f"Suite: {suite.name}   •   Diekspor: {datetime.now().strftime('%d %b %Y %H:%M')}   •   "
        f"Total {len(suite.test_cases)} TC   •   OK {ok_n}   •   NOK {nok_n}   •   Belum diuji {pending_n}"
    )
    sheet["A2"].font = Font(color="134E4A", name="Calibri", size=10)
    sheet["A2"].alignment = Alignment(vertical="center", indent=1)
    sheet.row_dimensions[2].height = 20

    for col, header in enumerate(HEADERS, start=1):
        cell = sheet.cell(3, col, header)
        cell.fill = header_fill
        cell.font = white
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin
    sheet.row_dimensions[3].height = 22
    sheet.auto_filter.ref = f"A3:I{3 + max(len(suite.test_cases), 1)}"
    sheet.freeze_panes = "A4"

    for row_idx, values in enumerate(_rows(suite), start=4):
        status = values[7]
        fill = ok_fill if status == "OK" else nok_fill if status == "NOK" else pending_fill
        sheet.row_dimensions[row_idx].height = 36
        for col, value in enumerate(values, start=1):
            cell = sheet.cell(row_idx, col, value)
            cell.alignment = wrap
            cell.border = thin
            cell.font = Font(name="Calibri", size=10)
            if col == 8:
                cell.fill = fill
                cell.font = Font(name="Calibri", size=11, bold=True, color="14532D" if status == "OK" else "7F1D1D" if status == "NOK" else "334155")
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif row_idx % 2 == 0:
                cell.fill = alt_fill

    widths = [14, 36, 20, 34, 16, 16, 42, 14, 46]
    for idx, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(idx)].width = width

    book.save(target)
    return target


def export_pdf(suite: TestSuite, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "JAQATitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=16,
        textColor=colors.HexColor("#0B3A4A"),
        alignment=TA_LEFT,
        spaceAfter=4,
    )
    meta_style = ParagraphStyle(
        "JAQAMeta",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        textColor=colors.HexColor("#115E67"),
        spaceAfter=10,
    )
    cell = ParagraphStyle(
        "JAQACell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#0F172A"),
    )
    cell_center = ParagraphStyle("JAQACellCenter", parent=cell, alignment=TA_CENTER, fontName="Helvetica-Bold")

    ok_n = sum(1 for tc in suite.test_cases if tc.status == "OK")
    nok_n = sum(1 for tc in suite.test_cases if tc.status == "NOK")
    pending_n = len(suite.test_cases) - ok_n - nok_n

    def p(text: str, style=cell) -> Paragraph:
        safe = (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
        return Paragraph(safe, style)

    header_style = ParagraphStyle(
        "JAQAHeader",
        parent=cell_center,
        textColor=colors.white,
        fontSize=8,
    )
    header = [p(h, header_style) for h in HEADERS]
    data = [header]
    status_colors: list[str] = []
    for values in _rows(suite):
        status = values[7]
        status_colors.append(status)
        styled = [p(v) for v in values]
        styled[7] = p(status, cell_center)
        data.append(styled)

    doc = SimpleDocTemplate(
        str(target),
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title="JAQA Laporan SIT",
        author="JAQA — Jalin Automate QA",
    )
    table = Table(
        data,
        colWidths=[22 * mm, 38 * mm, 28 * mm, 40 * mm, 24 * mm, 24 * mm, 48 * mm, 20 * mm, 48 * mm],
        repeatRows=1,
    )
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#115E67")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (7, 0), (7, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#94A3B8")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for idx, status in enumerate(status_colors, start=1):
        if status == "OK":
            commands.append(("BACKGROUND", (7, idx), (7, idx), colors.HexColor("#86EFAC")))
        elif status == "NOK":
            commands.append(("BACKGROUND", (7, idx), (7, idx), colors.HexColor("#FCA5A5")))
        else:
            commands.append(("BACKGROUND", (7, idx), (7, idx), colors.HexColor("#E2E8F0")))
        if idx % 2 == 0:
            commands.append(("BACKGROUND", (0, idx), (6, idx), colors.HexColor("#F0FDFA")))
            commands.append(("BACKGROUND", (8, idx), (8, idx), colors.HexColor("#F0FDFA")))
    table.setStyle(TableStyle(commands))

    story = [
        Paragraph("JAQA — Jalin Automate QA", title_style),
        Paragraph(
            f"Laporan Hasil SIT &nbsp;&nbsp;|&nbsp;&nbsp; {suite.name} &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"{datetime.now().strftime('%d %b %Y %H:%M')} &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"Total {len(suite.test_cases)} TC &nbsp;&nbsp;•&nbsp;&nbsp; OK {ok_n} &nbsp;&nbsp;•&nbsp;&nbsp; "
            f"NOK {nok_n} &nbsp;&nbsp;•&nbsp;&nbsp; Belum diuji {pending_n}",
            meta_style,
        ),
        table,
        Spacer(1, 8),
        Paragraph(
            "Status OK (hijau) = semua expected result sesuai. Status NOK (merah) = ada expected yang gagal; lihat kolom Catatan.",
            meta_style,
        ),
    ]
    doc.build(story)
    return target
