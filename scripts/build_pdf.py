#!/usr/bin/env python3
"""Generate a real PDF of the product from the markdown (one source of truth).
Run: python3 scripts/build_pdf.py  ->  store/product/70-AI-Specialists-for-Claude.pdf
"""
import re, pathlib
from fpdf import FPDF

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "store/product/70-AI-Specialists-for-Claude.md"
OUT = ROOT / "store/product/70-AI-Specialists-for-Claude.pdf"

INK = (26, 20, 48)      # near-black
PURPLE = (91, 33, 182)
ORANGE = (194, 65, 12)
MUT = (107, 94, 140)
QUOTE_BG = (246, 242, 253)

def clean(s):
    # strip markdown emphasis markers; keep plain text (core fonts = latin-1 only)
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"(?<!\*)\*(?!\*)(.+?)\*(?!\*)", r"\1", s)
    return s.encode("latin-1", "replace").decode("latin-1")

class PDF(FPDF):
    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUT)
        avail = self.w - self.l_margin - self.r_margin
        self.set_x(self.l_margin)
        self.cell(avail/2, 8, "70 AI Specialists for Claude", align="L")
        self.cell(avail/2, 8, f"{self.page_no()}", align="R")
        self.set_xy(self.l_margin, self.get_y() + 10)

pdf = PDF(format="A4")
pdf.set_auto_page_break(True, margin=18)
pdf.set_margins(18, 18, 18)

# ---- cover ----
pdf.add_page()
pdf.ln(70)
pdf.set_text_color(*ORANGE)
pdf.set_font("Helvetica", "B", 50)
pdf.cell(0, 20, "*", align="C")
pdf.ln(26)
pdf.set_text_color(*INK)
pdf.set_font("Helvetica", "B", 34)
pdf.cell(0, 16, "70 AI Specialists", align="C", new_x="LMARGIN", new_y="NEXT")
pdf.cell(0, 16, "for Claude", align="C", new_x="LMARGIN", new_y="NEXT")
pdf.ln(8)
pdf.set_text_color(*MUT)
pdf.set_font("Helvetica", "", 13)
pdf.multi_cell(0, 7, clean("Your entire expert team - copywriters, marketers, analysts, closers, coders - in one pack."), align="C")
pdf.ln(40)
pdf.set_font("Helvetica", "I", 10)
pdf.multi_cell(0, 6, "Copy-paste prompt pack - works in Claude.ai, the API & Claude Code", align="C")

# ---- body ----
pdf.add_page()
lines = SRC.read_text(encoding="utf-8").splitlines()
i = 0
while i < len(lines):
    raw = lines[i].rstrip(); i += 1
    if not raw.strip():
        continue
    pdf.set_x(pdf.l_margin)  # always start a block at the left margin
    if raw.startswith("# "):
        continue  # title already on cover
    if raw.startswith("## "):
        pdf.ln(3)
        pdf.set_text_color(*PURPLE)
        pdf.set_font("Helvetica", "B", 16)
        pdf.multi_cell(0, 9, clean(raw[3:]))
        pdf.set_draw_color(230, 226, 240)
        pdf.line(pdf.l_margin, pdf.get_y()+1, 210-pdf.r_margin, pdf.get_y()+1)
        pdf.ln(3)
    elif raw.startswith("### "):
        pdf.ln(2)
        pdf.set_text_color(*INK)
        pdf.set_font("Helvetica", "B", 12)
        pdf.multi_cell(0, 7, clean(raw[4:]))
    elif raw.startswith("---"):
        pdf.ln(2)
    elif raw.startswith("> "):
        # gather full quote (single line in our source)
        text = clean(raw[2:])
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(40, 35, 66)
        x0, y0 = pdf.get_x(), pdf.get_y()
        # measure height via split_only
        pdf.set_fill_color(*QUOTE_BG)
        pdf.multi_cell(0, 6, text, fill=True, border=0)
        pdf.ln(1)
    elif re.match(r"\*\*\d+\.", raw):
        pdf.ln(1.5)
        pdf.set_text_color(*ORANGE)
        pdf.set_font("Helvetica", "B", 11)
        pdf.multi_cell(0, 6, clean(raw))
    elif raw.startswith("- "):
        pdf.set_text_color(*INK)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 6, "  - " + clean(raw[2:]))
    else:
        pdf.set_text_color(*INK)
        pdf.set_font("Helvetica", "", 10)
        style = "I" if raw.startswith("*") and raw.endswith("*") else ""
        pdf.set_font("Helvetica", style, 10)
        pdf.multi_cell(0, 6, clean(raw))

pdf.output(str(OUT))
print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")
