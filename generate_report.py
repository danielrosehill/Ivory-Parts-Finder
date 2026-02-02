#!/usr/bin/env python3
"""
Generate a PDF report of the Ivory price analysis.
"""

import json
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak

SCRIPT_DIR = Path(__file__).parent
EXPORTS_DIR = SCRIPT_DIR / "exports"
CHARTS_DIR = SCRIPT_DIR / "charts"


def load_data():
    with open(EXPORTS_DIR / "ivory_products_latest.json") as f:
        return json.load(f)


def get_category_stats(data):
    """Extract category statistics."""
    stats = []
    all_ratios = []

    for group_name, group_cats in data["categories"].items():
        for cat_key, cat_data in group_cats.items():
            ratios = [p["price_ratio"] for p in cat_data["products"] if p.get("price_ratio")]
            if ratios:
                avg = sum(ratios) / len(ratios)
                all_ratios.extend(ratios)
                stats.append({
                    "category": cat_data["description"],
                    "count": len(ratios),
                    "avg": avg,
                })

    stats.sort(key=lambda x: x["avg"])
    overall_avg = sum(all_ratios) / len(all_ratios) if all_ratios else 0

    return stats, overall_avg, len(all_ratios)


def create_pdf():
    data = load_data()
    stats, overall_avg, total_products = get_category_stats(data)

    # Create PDF
    output_path = SCRIPT_DIR / "reports" / "ivory_price_analysis.pdf"
    output_path.parent.mkdir(exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=0.75*inch,
        leftMargin=0.75*inch,
        topMargin=0.75*inch,
        bottomMargin=0.75*inch
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=20,
        alignment=1  # Center
    )
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=16,
        spaceAfter=12
    )
    body_style = styles['Normal']

    elements = []

    # Title
    elements.append(Paragraph("Israeli Computer Parts Price Analysis", title_style))
    elements.append(Paragraph("Ivory.co.il vs US Retail Prices", styles['Heading2']))
    elements.append(Spacer(1, 20))

    # Summary
    capture_date = data["capture_date"][:10]
    exchange_rate = data["exchange_rate_ils_to_usd"]

    summary_text = f"""
    <b>Report Date:</b> {datetime.now().strftime('%Y-%m-%d')}<br/>
    <b>Data Captured:</b> {capture_date}<br/>
    <b>Exchange Rate:</b> 1 ILS = {exchange_rate} USD<br/>
    <b>Total Products:</b> {data['total_products']}<br/>
    <b>Products with Price Data:</b> {total_products}<br/>
    <b>Overall Average Ratio:</b> {overall_avg:.2f}x US prices
    """
    elements.append(Paragraph(summary_text, body_style))
    elements.append(Spacer(1, 30))

    # Key Findings
    elements.append(Paragraph("Key Findings", heading_style))
    findings = """
    • Most components are priced at 1.1x-1.6x US retail (reasonable import markup)<br/>
    • CPUs and GPUs are competitively priced at ~1.1-1.4x<br/>
    • Storage (SSDs, HDDs) has significant markup at ~2-2.7x<br/>
    • RAM has the highest markup at ~5.5x US prices
    """
    elements.append(Paragraph(findings, body_style))
    elements.append(Spacer(1, 20))

    # Price Ratio Chart
    elements.append(Paragraph("Price Ratio by Category", heading_style))
    chart_path = CHARTS_DIR / "price_ratio_by_category.png"
    if chart_path.exists():
        img = Image(str(chart_path), width=6*inch, height=4.8*inch)
        elements.append(img)

    elements.append(PageBreak())

    # Category Table
    elements.append(Paragraph("Detailed Category Breakdown", heading_style))
    elements.append(Spacer(1, 10))

    table_data = [["Category", "Products", "Avg Ratio"]]
    for s in stats:
        table_data.append([s["category"], str(s["count"]), f"{s['avg']:.2f}x"])
    table_data.append(["Overall", str(total_products), f"{overall_avg:.2f}x"])

    table = Table(table_data, colWidths=[3*inch, 1*inch, 1.2*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#ecf0f1')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#f8f9fa')]),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 30))

    # Distribution Chart
    elements.append(Paragraph("Price Distribution", heading_style))
    dist_path = CHARTS_DIR / "price_analysis_summary.png"
    if dist_path.exists():
        img = Image(str(dist_path), width=6.5*inch, height=3*inch)
        elements.append(img)

    elements.append(Spacer(1, 30))

    # Methodology
    elements.append(Paragraph("Methodology", heading_style))
    methodology = """
    <b>Data Collection:</b> Products scraped from ivory.co.il category pages<br/><br/>
    <b>US Price Estimation:</b> Google Gemini 2.0 Flash AI model estimates US retail prices
    based on product specifications and current market data. A two-pass verification process
    is used to improve accuracy.<br/><br/>
    <b>Price Ratio:</b> Israeli price (converted to USD) divided by estimated US RRP.
    A ratio of 1.0x means price parity; 2.0x means Israeli price is double US retail.<br/><br/>
    <b>Limitations:</b> US RRP estimates are AI-generated and may not reflect exact current prices.
    Exchange rates fluctuate. This analysis represents a point-in-time snapshot.
    """
    elements.append(Paragraph(methodology, body_style))

    # Build PDF
    doc.build(elements)
    print(f"PDF report saved to: {output_path}")
    return output_path


if __name__ == "__main__":
    create_pdf()
