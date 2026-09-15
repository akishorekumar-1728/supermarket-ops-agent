"""
documents/invoice.py
====================
GST Invoice PDF generator using ReportLab.

Generates a printable GST Tax Invoice PDF for finalized bills:
- Shop name (from preferences or default 'Supermarket Kirana Store')
- GSTIN (from preferences if configured)
- Invoice Number, Date/Time, Status, Payment Mode
- Clean Line-item table with columns:
  [# / Product / HSN / Qty / Unit Price / Taxable Amt / GST % / CGST / SGST / Line Total]
- Subtotal, CGST Total, SGST Total, Grand Total Summary
- Saves to generated/ directory and returns the absolute file path.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from tools.billing import BillNotFoundError, BillStateError, get_bill
from tools.preferences import get_preference

# Directory where generated PDF invoices will be stored
GENERATED_DIR = Path("generated").resolve()


def generate_invoice_pdf(
    bill_id: int | str,
    conn: sqlite3.Connection | None = None,
    output_dir: str | Path | None = None,
    **kwargs: Any,
) -> str:
    """
    Fetch a FINALIZED bill from SQLite and generate a real PDF tax invoice.

    Parameters:
        bill_id: Integer bill ID or invoice number string (e.g. 'INV-00001').
        conn: Open sqlite3.Connection.
        output_dir: Optional custom directory to save the PDF. Defaults to 'generated/'.

    Returns:
        str: Absolute file path to the generated PDF.

    Raises:
        BillNotFoundError: If bill cannot be found.
        BillStateError: If the bill is not in 'finalized' status.
    """
    c = conn or kwargs.get("conn")
    if c is None:
        raise ValueError("generate_invoice_pdf requires an open sqlite3.Connection (conn).")

    # Resolve bill_id if invoice number string was passed
    if isinstance(bill_id, str) and not bill_id.isdigit():
        row = c.execute(
            "SELECT id FROM bills WHERE invoice_number = ?", (bill_id.strip(),)
        ).fetchone()
        if not row:
            raise BillNotFoundError(f"Bill with invoice number {bill_id!r} not found.")
        actual_bill_id = int(row["id"])
    else:
        actual_bill_id = int(bill_id)

    bill = get_bill(actual_bill_id, c)

    if bill["status"] != "finalized":
        raise BillStateError(
            f"Cannot generate invoice PDF for unfinalized bill {actual_bill_id} "
            f"(status is '{bill['status']}'). Bill must be finalized first."
        )

    # Read shop preferences
    store_name = get_preference("store_name", default="Supermarket Kirana Store", conn=c)
    gstin = get_preference("gstin", default=None, conn=c)
    store_address = get_preference("store_address", default="Main Bazaar, Market Road", conn=c)
    store_phone = get_preference("store_phone", default="+91 98765 43210", conn=c)

    # Ensure output directory exists
    out_dir = Path(output_dir) if output_dir else GENERATED_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    inv_num = bill["invoice_number"] or f"BILL-{actual_bill_id}"
    safe_inv_num = inv_num.replace("/", "_").replace("\\", "_")
    pdf_path = out_dir / f"invoice_{safe_inv_num}.pdf"

    # Setup Document
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "ShopTitle",
        parent=styles["Heading1"],
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#1A365D"),
        fontName="Helvetica-Bold",
        alignment=1,  # Centered
    )

    subtitle_style = ParagraphStyle(
        "ShopSubtitle",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#4A5568"),
        alignment=1,  # Centered
    )

    header_style = ParagraphStyle(
        "InvoiceHeading",
        parent=styles["Heading2"],
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#2B6CB0"),
        fontName="Helvetica-Bold",
    )

    meta_label_style = ParagraphStyle(
        "MetaLabel",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#2D3748"),
        fontName="Helvetica-Bold",
    )

    meta_val_style = ParagraphStyle(
        "MetaVal",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#1A202C"),
    )

    cell_style = ParagraphStyle(
        "CellNormal",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#2D3748"),
    )

    cell_bold_style = ParagraphStyle(
        "CellBold",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#1A202C"),
    )

    cell_right_style = ParagraphStyle(
        "CellRight",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        alignment=2,  # Right aligned
        textColor=colors.HexColor("#2D3748"),
    )

    cell_right_bold = ParagraphStyle(
        "CellRightBold",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        alignment=2,  # Right aligned
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#1A202C"),
    )

    story = []

    # 1. Header: Store info
    story.append(Paragraph(store_name, title_style))
    subtitle_text = f"{store_address} | Phone: {store_phone}"
    if gstin:
        subtitle_text += f" | GSTIN: {gstin}"
    story.append(Paragraph(subtitle_text, subtitle_style))
    story.append(Spacer(1, 8))

    # Badge / Title
    story.append(
        Paragraph("TAX INVOICE (INTRA-STATE RETAIL SALE)", ParagraphStyle(
            "TaxInvBadge",
            parent=styles["Normal"],
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#2B6CB0"),
            fontName="Helvetica-Bold",
            alignment=1,
        ))
    )
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#2B6CB0"), spaceAfter=10))

    # 2. Invoice Meta Table
    finalized_time = bill["finalized_at"] or bill["created_at"] or "N/A"
    pay_mode = (bill["payment_mode"] or "Cash").upper()
    pay_ref = bill["payment_reference"] or "N/A"

    meta_data = [
        [
            Paragraph("Invoice Number:", meta_label_style),
            Paragraph(f"<b>{inv_num}</b>", meta_val_style),
            Paragraph("Date & Time:", meta_label_style),
            Paragraph(str(finalized_time), meta_val_style),
        ],
        [
            Paragraph("Payment Mode:", meta_label_style),
            Paragraph(f"<b>{pay_mode}</b>", meta_val_style),
            Paragraph("Payment Ref:", meta_label_style),
            Paragraph(str(pay_ref), meta_val_style),
        ],
    ]

    meta_table = Table(meta_data, colWidths=[1.3 * inch, 2.3 * inch, 1.1 * inch, 2.7 * inch])
    meta_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 10))

    # 3. Line Items Table
    headers = [
        Paragraph("#", cell_bold_style),
        Paragraph("Product Description", cell_bold_style),
        Paragraph("HSN", cell_bold_style),
        Paragraph("Qty", cell_right_bold),
        Paragraph("Rate (₹)", cell_right_bold),
        Paragraph("Taxable (₹)", cell_right_bold),
        Paragraph("GST", cell_right_bold),
        Paragraph("CGST (₹)", cell_right_bold),
        Paragraph("SGST (₹)", cell_right_bold),
        Paragraph("Total (₹)", cell_right_bold),
    ]

    table_data = [headers]

    for idx, it in enumerate(bill["items"], start=1):
        prod_name = it.get("name", "Product")
        sku = it.get("sku", "")
        desc = f"<b>{prod_name}</b><br/><font color='#718096' size='6.5'>SKU: {sku}</font>"
        hsn = str(it.get("hsn_code") or "N/A")
        qty_str = f"{it['quantity']} {it.get('unit', '')}"

        row_cells = [
            Paragraph(str(idx), cell_style),
            Paragraph(desc, cell_style),
            Paragraph(hsn, cell_style),
            Paragraph(qty_str, cell_right_style),
            Paragraph(f"{it['unit_price']:.2f}", cell_right_style),
            Paragraph(f"{it['taxable_amount']:.2f}", cell_right_style),
            Paragraph(f"{it['gst_rate']:.0f}%", cell_right_style),
            Paragraph(f"{it['cgst_amount']:.2f}", cell_right_style),
            Paragraph(f"{it['sgst_amount']:.2f}", cell_right_style),
            Paragraph(f"<b>{it['total']:.2f}</b>", cell_right_bold),
        ]
        table_data.append(row_cells)

    # Column widths (Total width ~ 7.4 inches)
    col_widths = [
        0.3 * inch,   # #
        2.2 * inch,   # Description
        0.55 * inch,  # HSN
        0.65 * inch,  # Qty
        0.65 * inch,  # Rate
        0.75 * inch,  # Taxable
        0.5 * inch,   # GST%
        0.6 * inch,   # CGST
        0.6 * inch,   # SGST
        0.75 * inch,  # Total
    ]

    items_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EBF8FF")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#2B6CB0")),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 10))

    # 4. Summary Totals Table
    subtotal = bill.get("subtotal", 0.0)
    cgst_tot = bill.get("cgst_total", 0.0)
    sgst_tot = bill.get("sgst_total", 0.0)
    gst_tot = bill.get("gst_total", 0.0)
    grand_tot = bill.get("grand_total", 0.0)

    summary_data = [
        [Paragraph("Taxable Amount (Subtotal):", cell_bold_style), Paragraph(f"₹ {subtotal:.2f}", cell_right_bold)],
        [Paragraph("CGST Total:", cell_style), Paragraph(f"₹ {cgst_tot:.2f}", cell_right_style)],
        [Paragraph("SGST Total:", cell_style), Paragraph(f"₹ {sgst_tot:.2f}", cell_right_style)],
        [Paragraph("Total GST Collected:", cell_style), Paragraph(f"₹ {gst_tot:.2f}", cell_right_style)],
        [
            Paragraph("<b>GRAND TOTAL:</b>", ParagraphStyle(
                "GrandTotLabel", parent=styles["Normal"], fontSize=10, leading=12, fontName="Helvetica-Bold", textColor=colors.HexColor("#1A365D")
            )),
            Paragraph(f"<b>₹ {grand_tot:.2f}</b>", ParagraphStyle(
                "GrandTotVal", parent=styles["Normal"], fontSize=11, leading=13, alignment=2, fontName="Helvetica-Bold", textColor=colors.HexColor("#1A365D")
            )),
        ],
    ]

    summary_table = Table(summary_data, colWidths=[2.2 * inch, 1.2 * inch])
    summary_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEABOVE", (0, -1), (-1, -1), 1.5, colors.HexColor("#1A365D")),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EBF8FF")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
    ]))

    # Align summary table to right
    outer_summary = Table([["", summary_table]], colWidths=[4.0 * inch, 3.4 * inch])
    outer_summary.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(outer_summary)
    story.append(Spacer(1, 15))

    # 5. Footer & Thank you note
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#CBD5E0"), spaceAfter=6))
    footer_style = ParagraphStyle(
        "Footer",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#718096"),
        alignment=1,
    )
    story.append(Paragraph("Thank you for shopping with us! Please retain this invoice for your records.", footer_style))
    story.append(Paragraph("This is a computer-generated tax invoice and requires no physical signature.", footer_style))

    # Build PDF
    doc.build(story)

    return str(pdf_path.resolve())
