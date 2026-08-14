#!/usr/bin/env python3
"""Generate markdown and PDF reports from Meta Ads analysis data."""

import argparse
import json
import os
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


def generate_html(markdown_text, report_data=None):
    """Convert markdown report to a styled, standalone HTML page."""
    name = ""
    if report_data:
        name = report_data.get("account_name", report_data.get("account_id", ""))

    # Convert markdown tables and headings to HTML manually
    html_body_lines = []
    in_table = False
    table_rows = []

    for line in markdown_text.split("\n"):
        stripped = line.strip()

        # Table separator row — skip
        if stripped.startswith("|") and "---" in stripped:
            continue

        # Table row
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            if not in_table:
                in_table = True
                table_rows = []
                # First row = header
                header_html = "".join(f"<th>{c}</th>" for c in cells)
                table_rows.append(f"<thead><tr>{header_html}</tr></thead><tbody>")
            else:
                row_html = "".join(f"<td>{c}</td>" for c in cells)
                table_rows.append(f"<tr>{row_html}</tr>")
            continue

        # End of table
        if in_table:
            table_rows.append("</tbody>")
            html_body_lines.append(f'<table>{"".join(table_rows)}</table>')
            in_table = False
            table_rows = []

        # Headings
        if stripped.startswith("# ") and not stripped.startswith("## "):
            html_body_lines.append(f"<h1>{stripped[2:]}</h1>")
        elif stripped.startswith("## "):
            html_body_lines.append(f"<h2>{stripped[3:]}</h2>")
        elif stripped.startswith("### "):
            html_body_lines.append(f"<h3>{stripped[4:]}</h3>")
        elif stripped.startswith("**") and stripped.endswith("**"):
            html_body_lines.append(f"<p><strong>{stripped.strip('*')}</strong></p>")
        elif stripped.startswith("- "):
            html_body_lines.append(f"<li>{stripped[2:]}</li>")
        elif stripped:
            html_body_lines.append(f"<p>{stripped}</p>")

    # Close any remaining table
    if in_table:
        table_rows.append("</tbody>")
        html_body_lines.append(f'<table>{"".join(table_rows)}</table>')

    body = "\n".join(html_body_lines)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Meta Ads Report{' — ' + name if name else ''}</title>
<style>
  :root {{
    --bg: #0f1117;
    --card: #1a1d27;
    --border: #2a2d3a;
    --text: #e4e4e7;
    --text-muted: #9ca3af;
    --accent: #6366f1;
    --accent-light: #818cf8;
    --green: #34d399;
    --red: #f87171;
    --yellow: #fbbf24;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 2rem;
    max-width: 1100px;
    margin: 0 auto;
  }}
  h1 {{
    font-size: 1.75rem;
    font-weight: 700;
    margin-bottom: 0.25rem;
    background: linear-gradient(135deg, var(--accent-light), var(--green));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }}
  h2 {{
    font-size: 1.25rem;
    font-weight: 600;
    margin-top: 2rem;
    margin-bottom: 0.75rem;
    color: var(--accent-light);
    border-bottom: 1px solid var(--border);
    padding-bottom: 0.4rem;
  }}
  h3 {{
    font-size: 1.05rem;
    font-weight: 600;
    margin-top: 1.25rem;
    margin-bottom: 0.5rem;
    color: var(--yellow);
  }}
  p {{ margin-bottom: 0.5rem; }}
  strong {{ color: var(--text); }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 0.75rem 0 1.25rem;
    background: var(--card);
    border-radius: 8px;
    overflow: hidden;
  }}
  thead {{ background: var(--border); }}
  th {{
    text-align: left;
    padding: 0.6rem 0.75rem;
    font-size: 0.8rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-muted);
  }}
  td {{
    padding: 0.55rem 0.75rem;
    border-top: 1px solid var(--border);
    font-size: 0.9rem;
  }}
  tr:hover td {{ background: rgba(99,102,241,0.06); }}
  li {{
    margin-left: 1.5rem;
    margin-bottom: 0.3rem;
    list-style: disc;
  }}
  @media (max-width: 768px) {{
    body {{ padding: 1rem; }}
    table {{ font-size: 0.8rem; }}
  }}
</style>
</head>
<body>
{body}
<footer style="margin-top:3rem; padding-top:1rem; border-top:1px solid var(--border); color:var(--text-muted); font-size:0.8rem;">
  Generated by claude-meta-ads plugin
</footer>
</body>
</html>"""


def write_file(path, content):
    """Write content to a file, creating directories if needed."""
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def generate_csv(report_data, output_dir):
    """Export report data as CSV files (one per section).

    Returns dict of section name -> file path.
    """
    import csv

    os.makedirs(output_dir, exist_ok=True)
    files = {}

    # Campaigns
    campaigns = report_data.get("campaigns", [])
    if campaigns:
        path = os.path.join(output_dir, "campaigns.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["name", "spend", "purchases", "revenue", "roas", "cpa", "ctr", "cpm"])
            writer.writeheader()
            writer.writerows(campaigns)
        files["campaigns"] = os.path.abspath(path)

    # Creatives
    creatives = report_data.get("creatives", [])
    if creatives:
        path = os.path.join(output_dir, "creatives.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["name", "format", "spend", "ctr", "cpa", "frequency", "fatigue"])
            writer.writeheader()
            writer.writerows(creatives)
        files["creatives"] = os.path.abspath(path)

    # Placements
    placements = report_data.get("placements", [])
    if placements:
        path = os.path.join(output_dir, "placements.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["name", "spend", "purchases", "cpa", "roas"])
            writer.writeheader()
            writer.writerows(placements)
        files["placements"] = os.path.abspath(path)

    return files


def _delta(current, previous, key, as_pct=False):
    """Calculate change between two values."""
    cur = current.get(key, 0)
    prev = previous.get(key, 0)
    diff = cur - prev
    if as_pct and prev:
        return {"current": cur, "previous": prev, "change": diff, "change_pct": round(diff / prev * 100, 1)}
    return {"current": cur, "previous": prev, "change": diff}


def generate_comparison(current_data, previous_data):
    """Generate a period-over-period comparison summary."""
    cur_s = current_data.get("summary", {})
    prev_s = previous_data.get("summary", {})

    comparison = {
        "current_period": current_data.get("date_range", ""),
        "previous_period": previous_data.get("date_range", ""),
        "metrics": {
            "spend": _delta(cur_s, prev_s, "spend", as_pct=True),
            "purchases": _delta(cur_s, prev_s, "purchases", as_pct=True),
            "revenue": _delta(cur_s, prev_s, "revenue", as_pct=True),
            "roas": _delta(cur_s, prev_s, "roas", as_pct=True),
            "cpa": _delta(cur_s, prev_s, "cpa", as_pct=True),
            "reach": _delta(cur_s, prev_s, "reach", as_pct=True),
        },
    }

    # Campaign-level comparison
    cur_campaigns = {c["name"]: c for c in current_data.get("campaigns", [])}
    prev_campaigns = {c["name"]: c for c in previous_data.get("campaigns", [])}
    all_names = sorted(set(list(cur_campaigns.keys()) + list(prev_campaigns.keys())))

    campaign_changes = []
    for name in all_names:
        cur = cur_campaigns.get(name, {})
        prev = prev_campaigns.get(name, {})
        campaign_changes.append({
            "name": name,
            "spend": _delta(cur, prev, "spend", as_pct=True),
            "roas": _delta(cur, prev, "roas", as_pct=True),
            "status": "new" if name not in prev_campaigns else ("removed" if name not in cur_campaigns else "active"),
        })
    comparison["campaigns"] = campaign_changes

    return comparison


def main():
    parser = argparse.ArgumentParser(description="Generate Meta Ads report")
    parser.add_argument("--input", required=True, help="Path to JSON report data file")
    parser.add_argument("--format", choices=["pdf", "md", "html", "csv", "both"], default="both",
                        help="Output format (default: both = md + pdf)")
    parser.add_argument("--output", help="Output file path (auto-generated if not set)")
    parser.add_argument("--compare", help="Path to previous period JSON for comparison")

    args = parser.parse_args()

    with open(args.input, "r") as f:
        report_data = json.load(f)

    account_id = report_data.get("account_id", "unknown")
    today = date.today().isoformat()
    base = args.output or f"meta-ads-report-{account_id}-{today}"

    outputs = {}

    # If comparing, merge comparison data into report
    if args.compare:
        with open(args.compare, "r") as f:
            previous_data = json.load(f)
        comparison = generate_comparison(report_data, previous_data)
        report_data["comparison"] = comparison

    md = generate_markdown(report_data)

    if args.format in ("md", "both"):
        md_path = f"{base}.md" if not base.endswith(".md") else base
        write_file(md_path, md)
        outputs["md"] = os.path.abspath(md_path)

    if args.format in ("pdf", "both"):
        pdf_path = f"{base}.pdf" if not base.endswith(".pdf") else base
        generate_pdf(md, pdf_path)
        outputs["pdf"] = os.path.abspath(pdf_path)

    if args.format == "html":
        html_path = f"{base}.html" if not base.endswith(".html") else base
        html = generate_html(md, report_data)
        write_file(html_path, html)
        outputs["html"] = os.path.abspath(html_path)

    if args.format == "csv":
        csv_dir = f"{base}-csv"
        csv_files = generate_csv(report_data, csv_dir)
        outputs["csv"] = csv_files

    result = {"status": "ok", "format": args.format, "outputs": outputs}
    if args.compare:
        result["comparison"] = report_data["comparison"]
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

