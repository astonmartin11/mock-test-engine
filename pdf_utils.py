"""
Converts a generated mock test (Markdown, student-visible section only)
into a downloadable PDF using fpdf2. Kept deliberately simple/robust:
we do lightweight Markdown-ish parsing (headers, rules, bold) rather
than pulling in a full Markdown-to-PDF pipeline.
"""

from __future__ import annotations
from fpdf import FPDF
import re


class MockTestPDF(FPDF):
    def header(self):
        pass  # no repeating header — keep it clean

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")


def _write_line(pdf: MockTestPDF, line: str) -> None:
    line = line.rstrip()

    if not line.strip():
        pdf.ln(3)
        return

    if line.startswith("# "):
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_text_color(20, 20, 20)
        pdf.multi_cell(0, 9, line[2:].strip())
        pdf.ln(1)
        return

    if line.startswith("## "):
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(30, 30, 30)
        pdf.ln(2)
        pdf.multi_cell(0, 8, line[3:].strip())
        pdf.ln(1)
        return

    if line.startswith("### "):
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(40, 40, 40)
        pdf.ln(2)
        pdf.multi_cell(0, 7, line[4:].strip())
        pdf.ln(1)
        return

    if line.strip() in ("---", "***", "___"):
        y = pdf.get_y()
        pdf.set_draw_color(180, 180, 180)
        pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
        pdf.ln(4)
        return

    # Bold markdown (**text**) -> stripped to plain bold-ish rendering.
    # fpdf2 multi_cell doesn't do inline mixed styling easily without
    # markdown=True support, so we use that flag directly:
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(0, 0, 0)
    pdf.multi_cell(0, 6, line, markdown=True)


def markdown_to_pdf_bytes(title: str, markdown_text: str) -> bytes:
    pdf = MockTestPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18, 16, 18)
    pdf.add_page()

    for raw_line in markdown_text.split("\n"):
        _write_line(pdf, raw_line)

    out = pdf.output()
    return bytes(out)


def evaluation_to_pdf_bytes(title: str, result_json: dict) -> bytes:
    """Render a graded evaluation JSON as a readable PDF report."""
    pdf = MockTestPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18, 16, 18)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(0, 9, title)
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 12)
    score_line = f"Score: {result_json.get('total_score', '?')} / {result_json.get('max_score', '?')}  ({result_json.get('percentage', '?')}%)"
    pdf.multi_cell(0, 7, score_line)
    pdf.ln(3)

    for q in result_json.get("question_evaluations", []):
        pdf.set_font("Helvetica", "B", 11)
        header = f"Q{q.get('question_number', '?')} [{q.get('topic_tag','')}] — {q.get('marks_awarded','?')}/{q.get('max_marks','?')}"
        if q.get("is_grey_area"):
            header += "  (GREY AREA)"
        pdf.multi_cell(0, 6, header)

        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 5, f"Strengths: {q.get('strengths','')}")
        pdf.multi_cell(0, 5, f"Errors/Gaps: {q.get('missing_concepts_or_errors','')}")
        pdf.multi_cell(0, 5, f"Remedial action: {q.get('remedial_action','')}")
        pdf.ln(3)

    pdf.set_font("Helvetica", "B", 11)
    pdf.multi_cell(0, 6, "Overall Summary")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 5, result_json.get("overall_summary", ""))

    out = pdf.output()
    return bytes(out)
