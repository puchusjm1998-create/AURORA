"""Generación de informes nativos en PDF y Excel.

Los datos llegan ya calculados desde la API en un :class:`ReportTable`; este módulo
solo se ocupa de la presentación. PDF se compone con ReportLab (tabla paginada,
cabecera repetida y pie con página) y Excel con openpyxl (hoja de resumen, cabecera
fija, autofiltro, formatos numéricos y fila de totales).
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

BRAND = colors.HexColor("#12314d")
ACCENT = colors.HexColor("#1f7a8c")
MUTED = colors.HexColor("#5b6b7a")
STRIPE = colors.HexColor("#f2f6fa")
LINE = colors.HexColor("#d5dee7")

XLSX_BRAND = "12314D"
XLSX_ACCENT = "1F7A8C"
XLSX_STRIPE = "F2F6FA"

#: Máximo de filas maquetadas en PDF para que el documento siga siendo manejable.
PDF_MAX_ROWS = 4000

NUMBER_FORMATS = {
    "qty": "#,##0.000",
    "money": "#,##0.00",
    "int": "#,##0",
}


@dataclass
class ReportTable:
    """Datos tabulares listos para representar."""

    title: str
    subtitle: str
    headers: list[str]
    rows: list[list[Any]]
    formats: dict[int, str] = field(default_factory=dict)
    totals: list[Any] | None = None
    meta: list[tuple[str, str]] = field(default_factory=list)
    sheet_name: str = "Datos"


def select_columns(table: ReportTable, indexes: Sequence[int]) -> ReportTable:
    """Devuelve una vista con un subconjunto de columnas (para PDF compacto)."""
    headers = [table.headers[index] for index in indexes]
    rows = [[row[index] for index in indexes] for row in table.rows]
    totals = [table.totals[index] for index in indexes] if table.totals else None
    formats = {
        position: table.formats[index]
        for position, index in enumerate(indexes)
        if index in table.formats
    }
    return ReportTable(
        title=table.title,
        subtitle=table.subtitle,
        headers=headers,
        rows=rows,
        formats=formats,
        totals=totals,
        meta=table.meta,
        sheet_name=table.sheet_name,
    )


# --------------------------------------------------------------------------- #
# Formato es-ES
# --------------------------------------------------------------------------- #
def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def format_number(value: Any, kind: str = "qty") -> str:
    """Formatea un número con separadores españoles (1.234,500 / 1.234,50)."""
    number = _decimal(value)
    if number is None:
        return str(value) if value not in (None, "") else ""
    places = {"qty": 3, "money": 2, "int": 0}.get(kind, 2)
    text = f"{number:,.{places}f}"
    return text.replace(",", "\u00a0").replace(".", ",").replace("\u00a0", ".")


def _display(value: Any, kind: str | None) -> str:
    if kind in NUMBER_FORMATS:
        return format_number(value, kind)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M")
    return "" if value is None else str(value)


def _csv_value(value: Any, kind: str | None) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if kind in ("qty", "money") and _decimal(value) is not None:
        return f"{_decimal(value):.3f}" if kind == "qty" else f"{_decimal(value):.2f}"
    return _display(value, kind)


def table_as_csv_rows(table: ReportTable) -> list[list[str]]:
    return [
        [_csv_value(value, table.formats.get(index)) for index, value in enumerate(row)]
        for row in table.rows
    ]


def _generated_at(moment: datetime | None = None) -> datetime:
    return (moment or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _subtitle_with_cap(table: ReportTable, count: int) -> str:
    if count > PDF_MAX_ROWS:
        return (
            f"{table.subtitle} · Mostrando {PDF_MAX_ROWS:,} de {count:,} filas; "
            "use Excel o CSV para el detalle completo."
        ).replace(",", ".")
    return table.subtitle


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #
def render_pdf(table: ReportTable, *, moment: datetime | None = None) -> bytes:
    generated = _generated_at(moment)
    rows = table.rows[:PDF_MAX_ROWS]
    buffer = io.BytesIO()
    page_size = landscape(A4)
    margin = 12 * mm
    document = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=16 * mm,
        title=table.title,
        author="AURORA LOGISTICS AI",
        subject=table.subtitle,
    )

    cell_style = ParagraphStyle(
        "cell", fontName="Helvetica", fontSize=6.8, leading=8.2, textColor=colors.HexColor("#1b2733")
    )
    cell_right = ParagraphStyle("cellr", parent=cell_style, alignment=2)
    head_style = ParagraphStyle(
        "head", fontName="Helvetica-Bold", fontSize=7, leading=8.4, textColor=colors.white
    )
    head_right = ParagraphStyle("headr", parent=head_style, alignment=2)
    title_style = ParagraphStyle(
        "title", fontName="Helvetica-Bold", fontSize=16, leading=19, textColor=BRAND, spaceAfter=2
    )
    subtitle_style = ParagraphStyle(
        "subtitle", fontName="Helvetica", fontSize=8.5, leading=11, textColor=MUTED, spaceAfter=6
    )
    meta_style = ParagraphStyle(
        "meta", fontName="Helvetica", fontSize=7.5, leading=10, textColor=MUTED, alignment=TA_LEFT
    )

    story: list[Any] = [Paragraph(table.title, title_style)]
    story.append(Paragraph(_subtitle_with_cap(table, len(table.rows)), subtitle_style))
    meta_parts = [f"<b>Generado:</b> {generated.strftime('%d/%m/%Y %H:%M UTC')}"]
    meta_parts.extend(f"<b>{label}:</b> {value}" for label, value in table.meta)
    if table.rows:
        meta_parts.append(f"<b>Filas:</b> {len(table.rows):,}".replace(",", "."))
    story.append(Paragraph("&nbsp;&nbsp;·&nbsp;&nbsp;".join(meta_parts), meta_style))
    story.append(Spacer(1, 5 * mm))

    numeric = {index for index in table.formats}
    header_row = [
        Paragraph(header, head_right if index in numeric else head_style)
        for index, header in enumerate(table.headers)
    ]
    body: list[list[Any]] = [header_row]
    for row in rows:
        body.append(
            [
                Paragraph(
                    _display(value, table.formats.get(index)),
                    cell_right if index in numeric else cell_style,
                )
                for index, value in enumerate(row)
            ]
        )
    if table.totals:
        body.append(
            [
                Paragraph(
                    f"<b>{_display(value, None) if index else 'Total'}</b>",
                    ParagraphStyle("tot", parent=cell_right if index in numeric else cell_style,
                                   fontName="Helvetica-Bold"),
                )
                for index, value in enumerate(table.totals)
            ]
        )

    usable = page_size[0] - 2 * margin
    weights = [max(len(header), 7) for header in table.headers]
    for index in numeric:
        weights[index] = max(6, weights[index] - 4)
    scale = usable / sum(weights)
    widths = [weight * scale for weight in weights]
    grid = LongTable(body, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, STRIPE]),
        ("GRID", (0, 0), (-1, -1), 0.25, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.4),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    # Repetir el fondo de cabecera en cada página.
    style.append(("BACKGROUND", (0, 0), (-1, 0), BRAND))
    style.append(("LINEBELOW", (0, 0), (-1, 0), 1, ACCENT))
    if table.totals:
        style.append(("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e6eef5")))
        style.append(("LINEABOVE", (0, -1), (-1, -1), 0.8, ACCENT))
    grid.setStyle(TableStyle(style))
    story.append(grid)

    footer = (
        f"AURORA LOGISTICS AI · {table.title} · {generated.strftime('%d/%m/%Y %H:%M UTC')}"
    )

    def decorate(canvas, doc) -> None:  # noqa: ANN001 - firma de ReportLab
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.4)
        canvas.line(margin, 12 * mm, page_size[0] - margin, 12 * mm)
        canvas.setFont("Helvetica", 6.8)
        canvas.setFillColor(MUTED)
        canvas.drawString(margin, 7.5 * mm, footer)
        canvas.drawRightString(page_size[0] - margin, 7.5 * mm, f"Página {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# Excel
# --------------------------------------------------------------------------- #
def render_xlsx(
    table: ReportTable,
    *,
    moment: datetime | None = None,
    extra_sheets: Iterable[tuple[str, list[list[Any]]]] | None = None,
) -> bytes:
    generated = _generated_at(moment)
    workbook = Workbook()
    workbook.properties.creator = "AURORA LOGISTICS AI"
    workbook.properties.title = table.title
    workbook.properties.description = table.subtitle

    summary = workbook.active
    summary.title = "Resumen"
    summary_widths = {"A": 26, "B": 46, "C": 18, "D": 18}
    for column, width in summary_widths.items():
        summary.column_dimensions[column].width = width
    summary["A1"] = table.title
    summary["A1"].font = Font(name="Calibri", size=16, bold=True, color=XLSX_BRAND)
    summary.merge_cells("A1:D1")
    summary["A2"] = table.subtitle
    summary["A2"].font = Font(size=10, italic=True, color="5B6B7A")
    summary.merge_cells("A2:D2")
    summary["A4"] = "Generado (UTC)"
    summary["B4"] = generated.strftime("%d/%m/%Y %H:%M")
    summary["A5"] = "Filas exportadas"
    summary["B5"] = len(table.rows)
    summary["A6"] = "Formato"
    summary["B6"] = "Excel nativo (.xlsx)"
    row = 8
    for label, value in table.meta:
        summary[f"A{row}"] = label
        summary[f"B{row}"] = value
        row += 1
    for label_cell in summary["A"]:
        label_cell.font = Font(bold=True, color=XLSX_BRAND)
    summary["A1"].font = Font(size=16, bold=True, color=XLSX_BRAND)
    summary["A2"].font = Font(size=10, italic=True, color="5B6B7A")
    summary.freeze_panes = "A4"

    sheet = workbook.create_sheet(table.sheet_name[:31] or "Datos")
    header_fill = PatternFill("solid", fgColor=XLSX_BRAND)
    stripe_fill = PatternFill("solid", fgColor=XLSX_STRIPE)
    header_font = Font(bold=True, color="FFFFFF", size=10)
    thin = Side(style="thin", color="D5DEE7")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for column, header in enumerate(table.headers, start=1):
        cell = sheet.cell(row=1, column=column, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border
    sheet.row_dimensions[1].height = 26
    sheet.freeze_panes = "A2"

    for row_index, data_row in enumerate(table.rows, start=2):
        for column, value in enumerate(data_row, start=1):
            kind = table.formats.get(column - 1)
            cell = sheet.cell(row=row_index, column=column)
            if kind in NUMBER_FORMATS and _decimal(value) is not None:
                cell.value = float(_decimal(value))
                cell.number_format = NUMBER_FORMATS[kind]
                cell.alignment = Alignment(horizontal="right", vertical="top")
            elif isinstance(value, datetime):
                cell.value = value.astimezone(timezone.utc).replace(tzinfo=None)
                cell.number_format = "DD/MM/YYYY HH:MM"
                cell.alignment = Alignment(horizontal="left", vertical="top")
            else:
                cell.value = "" if value is None else str(value)
                cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=False)
            cell.border = border
            if row_index % 2 == 0:
                cell.fill = stripe_fill

    last_data_row = max(1, len(table.rows) + 1)
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(table.headers))}{last_data_row}"
    if table.totals:
        total_row = last_data_row + 1
        for column, value in enumerate(table.totals, start=1):
            kind = table.formats.get(column - 1)
            cell = sheet.cell(row=total_row, column=column)
            if kind in NUMBER_FORMATS and _decimal(value) is not None:
                cell.value = float(_decimal(value))
                cell.number_format = NUMBER_FORMATS[kind]
                cell.alignment = Alignment(horizontal="right")
            else:
                cell.value = "" if value is None else str(value)
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor="E6EEF5")
            cell.border = Border(top=Side(style="medium", color=XLSX_ACCENT))
        sheet.auto_filter.ref = f"A1:{get_column_letter(len(table.headers))}{last_data_row}"

    for column, header in enumerate(table.headers, start=1):
        longest = max([len(str(header))] + [len(_display(row[column - 1], None)) for row in table.rows[:500]])
        sheet.column_dimensions[get_column_letter(column)].width = min(42, max(10, longest + 2))

    for title, matrix in extra_sheets or []:
        extra = workbook.create_sheet(title[:31])
        for row_index, data_row in enumerate(matrix, start=1):
            for column, value in enumerate(data_row, start=1):
                extra.cell(row=row_index, column=column, value=value)
        if matrix:
            for cell in extra[1]:
                cell.font = Font(bold=True)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def attachment_headers(filename: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{filename}"'}
