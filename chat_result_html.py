"""Safe HTML rendering for CSAT chat answers and their email sharing."""
from __future__ import annotations

import html
import re

def _inline_markdown(value: object) -> str:
    """Render a small safe subset of Markdown after escaping source text."""
    text = html.escape(str(value if value is not None else ""), quote=True)
    # Inline code first, then bold/italic. Inputs are escaped before markup is added.
    text = re.sub(r"`([^`]+)`", r'<code style="background:#eef2f7;padding:2px 4px;border-radius:4px">\1</code>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    return text


def _table_cells(line: str) -> list[str]:
    trimmed = line.strip()
    if trimmed.startswith("|"):
        trimmed = trimmed[1:]
    if trimmed.endswith("|"):
        trimmed = trimmed[:-1]
    return [cell.replace("\\|", "|").strip() for cell in re.split(r"(?<!\\)\|", trimmed)]


def _is_table_separator(line: str) -> bool:
    cells = _table_cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def markdown_answer_to_html(markdown_text: str) -> str:
    """Convert typical assistant Markdown (headings, lists, and tables) to safe HTML."""
    lines = str(markdown_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    paragraph: list[str] = []
    list_kind: str | None = None

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            inner = "<br>".join(_inline_markdown(part) for part in paragraph)
            out.append(f'<p style="margin:8px 0 12px;line-height:1.55;color:#334155">{inner}</p>')
            paragraph = []

    def close_list() -> None:
        nonlocal list_kind
        if list_kind:
            out.append(f"</{list_kind}>")
            list_kind = None

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            close_list()
            i += 1
            continue

        # Markdown tables: a header, a separator row, then zero or more data rows.
        if "|" in stripped and i + 1 < len(lines) and _is_table_separator(lines[i + 1]):
            flush_paragraph()
            close_list()
            headers = _table_cells(stripped)
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                rows.append(_table_cells(lines[i]))
                i += 1
            ths = "".join(
                '<th align="left" style="background:#eaf0f8;color:#1e293b;border-bottom:1px solid #d7e0eb;padding:9px 10px;font-size:12px">'
                + _inline_markdown(cell) + "</th>" for cell in headers
            )
            trs = []
            for row_index, row in enumerate(rows):
                bg = "#ffffff" if row_index % 2 == 0 else "#f8fafc"
                cells = []
                for col_index in range(len(headers)):
                    value = row[col_index] if col_index < len(row) else ""
                    cells.append(
                        f'<td valign="top" style="background:{bg};border-bottom:1px solid #e7edf4;padding:8px 10px;color:#334155;font-size:12px;line-height:1.45">'
                        + _inline_markdown(value) + "</td>"
                    )
                trs.append("<tr>" + "".join(cells) + "</tr>")
            out.append(
                '<div style="width:100%;overflow-x:auto;margin:10px 0 14px"><table role="table" cellpadding="0" cellspacing="0" '
                'style="width:100%;border-collapse:collapse;border:1px solid #dbe3ed">'
                f"<thead><tr>{ths}</tr></thead><tbody>{''.join(trs)}</tbody></table></div>"
            )
            continue

        heading = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if heading:
            flush_paragraph()
            close_list()
            level = min(len(heading.group(1)) + 1, 4)
            out.append(
                f'<h{level} style="margin:14px 0 6px;color:#0f2744;font-size:{21 - level}px">'
                f'{_inline_markdown(heading.group(2))}</h{level}>'
            )
            i += 1
            continue

        bullet = re.match(r"^[-*+]\s+(.+)$", stripped)
        numbered = re.match(r"^\d+[.)]\s+(.+)$", stripped)
        if bullet or numbered:
            flush_paragraph()
            wanted = "ul" if bullet else "ol"
            if list_kind != wanted:
                close_list()
                out.append(f'<{wanted} style="margin:8px 0 14px;padding-left:22px;color:#334155;line-height:1.55">')
                list_kind = wanted
            item = (bullet or numbered).group(1)
            out.append(f"<li style=\"margin:3px 0\">{_inline_markdown(item)}</li>")
            i += 1
            continue

        close_list()
        paragraph.append(stripped)
        i += 1

    flush_paragraph()
    close_list()
    return "\n".join(out) if out else '<p style="color:#64748b">No answer was returned.</p>'


def render_chat_result_html(question: str, answer: str, start_date: str = "", end_date: str = "") -> str:
    """Create an email/client-friendly HTML card for an assistant answer."""
    period = f"{start_date} to {end_date}" if start_date and end_date else "Selected feedback"
    q = html.escape(str(question or ""), quote=True)
    content = markdown_answer_to_html(answer)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{{margin:0;background:#f1f5f9;font-family:Arial,Helvetica,sans-serif;color:#0f172a}} .wrap{{max-width:1000px;margin:0 auto;padding:12px}} .card{{background:#fff;border:1px solid #dbe3ed;border-radius:12px;overflow:hidden}} .head{{padding:16px 20px;background:#102a43;color:#fff}} .title{{font-size:17px;font-weight:700;line-height:1.35}} .period{{margin-top:5px;color:#d8e4f0;font-size:12px}} .body{{padding:16px 20px}} .question{{padding:10px 12px;margin-bottom:14px;background:#eff6ff;border-left:4px solid #2563eb;border-radius:4px;color:#1e3a8a;font-size:13px;line-height:1.5}} .footer{{border-top:1px solid #e2e8f0;padding:11px 20px;color:#64748b;font-size:11px;line-height:1.45}}</style></head>
<body><div class="wrap"><section class="card"><header class="head"><div class="title">CSAT Chat Assistant — Result</div><div class="period">Date range: {html.escape(period)}</div></header>
<div class="body"><div class="question"><strong>Question</strong><br>{q}</div><div class="answer">{content}</div></div>
<footer class="footer">Generated from the selected customer-feedback data. AI interpretations and root-cause suggestions are hypotheses and should be validated against operational evidence before decisions are made.</footer></section></div></body></html>"""


def render_chat_result_plain_text(question: str, answer: str, start_date: str = "", end_date: str = "") -> str:
    period = f"{start_date} to {end_date}" if start_date and end_date else "Selected feedback"
    return (
        "CSAT Chat Assistant — Result\n"
        f"Date range: {period}\n\n"
        f"Question: {question}\n\n"
        f"{answer}\n\n"
        "Note: AI interpretations and root-cause suggestions are hypotheses and should be validated against operational evidence."
    )
