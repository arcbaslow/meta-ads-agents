#!/usr/bin/env python3
"""Generate markdown and PDF reports from Meta Ads analysis data."""

import argparse
import json
import os
import sys
from datetime import date


def fmt_money(v):
    """Format a number as $X,XXX.XX."""
    return f"${v:,.2f}"


def fmt_num(v):
    """Format a number with commas."""
    if isinstance(v, float):
        return f"{v:,.2f}"
    return f"{v:,}"


def fmt_pct(v):
    """Format a number as percentage."""
    return f"{v:.2f}%"


def md_table(headers, rows):
    """Build a markdown pipe table from headers and row dicts/lists."""
    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        if isinstance(row, dict):
            cells = [str(row.get(h, "")) for h in headers]
        else:
            cells = [str(c) for c in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def generate_markdown(report_data):
    """Generate a markdown report from structured report data."""
    name = report_data.get("account_name", report_data.get("account_id", "Unknown"))
    date_range = report_data.get("date_range", "")
    s = report_data.get("summary", {})

    lines = []
    lines.append(f"# Meta Ads Report — {name}")
    lines.append(f"**{date_range}**\n")

    # Account summary
    lines.append("## Account summary\n")
    summary_rows = []
    if s:
        summary_rows.append(["Spend", fmt_money(s.get("spend", 0))])
        summary_rows.append(["Purchases", fmt_num(s.get("purchases", 0))])
        summary_rows.append(["Revenue", fmt_money(s.get("revenue", 0))])
        summary_rows.append(["ROAS", f"{s.get('roas', 0):.1f}x"])
        summary_rows.append(["CPA", fmt_money(s.get("cpa", 0))])
        summary_rows.append(["Reach", fmt_num(s.get("reach", 0))])
    lines.append(md_table(["Metric", "Value"], summary_rows))
    lines.append("")

    # Campaign performance
    campaigns = report_data.get("campaigns", [])
    if campaigns:
        lines.append("## Campaign performance\n")
        headers = ["Campaign", "Spend", "Purchases", "Revenue", "ROAS", "CPA", "CTR", "CPM"]
        rows = []
        for c in campaigns:
            rows.append([
                c.get("name", ""),
                fmt_money(c.get("spend", 0)),
                fmt_num(c.get("purchases", 0)),
                fmt_money(c.get("revenue", 0)),
                f"{c.get('roas', 0):.1f}x",
                fmt_money(c.get("cpa", 0)),
                fmt_pct(c.get("ctr", 0)),
                fmt_money(c.get("cpm", 0)),
            ])
        lines.append(md_table(headers, rows))
        lines.append("")

    # Creative performance
    creatives = report_data.get("creatives", [])
    if creatives:
        lines.append("## Creative performance\n")
        headers = ["Ad", "Format", "Spend", "CTR", "CPA", "Frequency", "Fatigue"]
        rows = []
        for c in creatives:
            rows.append([
                c.get("name", ""),
                c.get("format", ""),
                fmt_money(c.get("spend", 0)),
                fmt_pct(c.get("ctr", 0)),
                fmt_money(c.get("cpa", 0)),
                f"{c.get('frequency', 0):.2f}",
                c.get("fatigue", ""),
            ])
        lines.append(md_table(headers, rows))
        lines.append("")

    # Placement breakdown
    placements = report_data.get("placements", [])
    if placements:
        lines.append("## Placement breakdown\n")
        headers = ["Placement", "Spend", "Purchases", "CPA", "ROAS"]
        rows = []
        for p in placements:
            rows.append([
                p.get("name", ""),
                fmt_money(p.get("spend", 0)),
                fmt_num(p.get("purchases", 0)),
                fmt_money(p.get("cpa", 0)),
                f"{p.get('roas', 0):.0f}x",
            ])
        lines.append(md_table(headers, rows))
        lines.append("")

    # Age breakdown
    age_data = report_data.get("age_breakdown", [])
    if age_data:
        lines.append("## Age breakdown\n")
        headers = ["Age", "Spend", "Purchases", "CPA", "ROAS"]
        rows = []
        for a in age_data:
            rows.append([
                a.get("age", ""),
                fmt_money(a.get("spend", 0)),
                fmt_num(a.get("purchases", 0)),
                fmt_money(a.get("cpa", 0)),
                f"{a.get('roas', 0):.0f}x",
            ])
        lines.append(md_table(headers, rows))
        lines.append("")

    # Gender breakdown
    gender_data = report_data.get("gender_breakdown", [])
    if gender_data:
        lines.append("## Gender breakdown\n")
        headers = ["Gender", "Spend", "Purchases", "CPA", "ROAS"]
        rows = []
        for g in gender_data:
            rows.append([
                g.get("gender", ""),
                fmt_money(g.get("spend", 0)),
                fmt_num(g.get("purchases", 0)),
                fmt_money(g.get("cpa", 0)),
                f"{g.get('roas', 0):.0f}x",
            ])
        lines.append(md_table(headers, rows))
        lines.append("")

    # Tracking health
    tracking = report_data.get("tracking", {})
    if tracking:
        lines.append("## Tracking health\n")
        lines.append(f"- Pixel: {tracking.get('pixel_status', 'Unknown')}")
        lines.append(f"- CAPI: {'Active' if tracking.get('has_capi') else 'Not configured'}")
        lines.append(f"- Funnel: {tracking.get('funnel_health', 'Unknown')}")
        lines.append("")

    # Action plan
    actions = report_data.get("actions", [])
    if actions:
        lines.append("## Action plan\n")
        for level in ["critical", "high", "medium", "low"]:
            level_actions = [a for a in actions if a.get("level") == level]
            if level_actions:
                lines.append(f"### {level.upper()}\n")
                for a in level_actions:
                    lines.append(f"- {a['text']}")
                lines.append("")

    return "\n".join(lines)


def _sanitize(text):
    """Replace non-latin-1 characters with ASCII equivalents for built-in PDF fonts."""
    return (text
            .replace("\u2014", "--")   # em dash
            .replace("\u2013", "-")    # en dash
            .replace("\u2018", "'")    # left single quote
            .replace("\u2019", "'")    # right single quote
            .replace("\u201c", '"')    # left double quote
            .replace("\u201d", '"')    # right double quote
            .encode("latin-1", errors="replace").decode("latin-1"))


def generate_pdf(markdown_text, output_path):
    """Convert markdown text to PDF using fpdf2."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    for line in markdown_text.split("\n"):
        stripped = line.strip()

        if stripped.startswith("# ") and not stripped.startswith("## "):
            pdf.set_font("Helvetica", "B", 16)
            pdf.cell(0, 10, _sanitize(stripped[2:]), new_x="LMARGIN", new_y="NEXT")
        elif stripped.startswith("## "):
            pdf.ln(4)
            pdf.set_font("Helvetica", "B", 13)
            pdf.cell(0, 8, _sanitize(stripped[3:]), new_x="LMARGIN", new_y="NEXT")
        elif stripped.startswith("### "):
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 7, _sanitize(stripped[4:]), new_x="LMARGIN", new_y="NEXT")
        elif stripped.startswith("**") and stripped.endswith("**"):
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 6, _sanitize(stripped.strip("*")), new_x="LMARGIN", new_y="NEXT")
        elif stripped.startswith("|") and "---" not in stripped:
            # Table row
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            pdf.set_font("Helvetica", "", 8)
            col_w = (pdf.w - 20) / max(len(cells), 1)
            for cell in cells:
                pdf.cell(col_w, 5, _sanitize(cell), border=1)
            pdf.ln()
        elif stripped.startswith("- "):
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(5)
            pdf.cell(0, 6, _sanitize(stripped), new_x="LMARGIN", new_y="NEXT")
        elif stripped:
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(0, 6, _sanitize(stripped), new_x="LMARGIN", new_y="NEXT")

    pdf.output(output_path)


def write_file(path, content):
    """Write content to a file, creating directories if needed."""
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def main():
    parser = argparse.ArgumentParser(description="Generate Meta Ads report")
    parser.add_argument("--input", required=True, help="Path to JSON report data file")
    parser.add_argument("--format", choices=["pdf", "md", "both"], default="both",
                        help="Output format (default: both)")
    parser.add_argument("--output", help="Output file path (auto-generated if not set)")
    parser.add_argument("--json", action="store_true", default=True)

    args = parser.parse_args()

    with open(args.input, "r") as f:
        report_data = json.load(f)

    md = generate_markdown(report_data)
    account_id = report_data.get("account_id", "unknown")
    today = date.today().isoformat()
    base = args.output or f"meta-ads-report-{account_id}-{today}"

    outputs = {}

    if args.format in ("md", "both"):
        md_path = f"{base}.md" if not base.endswith(".md") else base
        write_file(md_path, md)
        outputs["md"] = os.path.abspath(md_path)

    if args.format in ("pdf", "both"):
        pdf_path = f"{base}.pdf" if not base.endswith(".pdf") else base
        generate_pdf(md, pdf_path)
        outputs["pdf"] = os.path.abspath(pdf_path)

    result = {"status": "ok", "format": args.format, "outputs": outputs}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
