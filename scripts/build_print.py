#!/usr/bin/env python3
"""Build a print-ready HTML (Cmd+P -> Save as PDF) from the product markdown.
One source of truth: store/product/70-AI-Specialists-for-Claude.md
Run: python3 scripts/build_print.py
"""
import re, html, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "store/product/70-AI-Specialists-for-Claude.md"
OUT = ROOT / "store/print.html"

lines = SRC.read_text(encoding="utf-8").splitlines()
body, in_quote = [], False

def esc(s): return html.escape(s)
def bold(s):  # **x** -> <strong>
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc(s))
def ital(s):
    return re.sub(r"(?<!\*)\*(?!\*)(.+?)\*(?!\*)", r"<em>\1</em>", s)

for raw in lines:
    line = raw.rstrip()
    if line.startswith("> "):
        if not in_quote:
            body.append('<blockquote>'); in_quote = True
        body.append(ital(bold(line[2:])) + " ")
        continue
    if in_quote:
        body.append('</blockquote>'); in_quote = False
    if not line.strip():
        continue
    if line.startswith("# "):
        body.append(f'<h1 class="cover-title">{bold(line[2:])}</h1>')
    elif line.startswith("## "):
        body.append(f'<h2>{bold(line[3:])}</h2>')
    elif line.startswith("### "):
        body.append(f'<h3>{bold(line[4:])}</h3>')
    elif line.startswith("---"):
        body.append('<hr/>')
    elif line.startswith("**") and re.match(r"\*\*\d+\.", line):
        body.append(f'<p class="spec">{bold(line)}</p>')
    elif line.startswith("- "):
        body.append(f'<li>{ital(bold(line[2:]))}</li>')
    elif line.startswith("> "):
        pass
    else:
        body.append(f'<p>{ital(bold(line))}</p>')
if in_quote: body.append('</blockquote>')

html_doc = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/>
<title>70 AI Specialists for Claude</title>
<style>
@page { size: A4; margin: 18mm 16mm; }
* { box-sizing: border-box; }
html { background:#fff; }
body { font: 11pt/1.55 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  color:#1a1430; background:#fff; max-width:760px; margin:0 auto; padding:24px; }
.cover { text-align:center; padding:120px 0 90px; page-break-after:always; }
.cover .star { font-size:54px; color:#ff7a18; }
.cover-title { font-size:30pt; font-weight:900; letter-spacing:-.5px; margin:14px 0; color:#1a1430; }
.cover .tag { color:#6b5e8c; font-size:13pt; max-width:420px; margin:0 auto; }
.cover .meta { margin-top:60px; color:#8a7da8; font-size:10pt; }
h2 { font-size:18pt; font-weight:900; color:#5b21b6; margin:28px 0 6px;
  padding-bottom:6px; border-bottom:2px solid #eee; page-break-after:avoid; }
h3 { font-size:12pt; color:#1a1430; margin:18px 0 6px; }
p { margin:6px 0; }
p.spec { font-weight:700; margin-top:14px; page-break-after:avoid; }
p.spec strong { color:#c2410c; }
blockquote { margin:4px 0 10px; padding:10px 14px; background:#f6f2fd;
  border-left:3px solid #8b5cf6; border-radius:0 8px 8px 0; font-size:10.5pt;
  color:#2a2342; page-break-inside:avoid; }
hr { border:none; border-top:1px solid #ece7f5; margin:22px 0; }
li { margin:4px 0 4px 18px; font-size:10.5pt; }
em { color:#6b5e8c; }
@media print { body { padding:0; } a { color:inherit; text-decoration:none; } }
.hint { background:#fff7ed; border:1px solid #fed7aa; color:#9a3412; padding:12px 16px;
  border-radius:10px; font-size:10pt; margin-bottom:20px; }
@media print { .hint { display:none; } }
</style></head><body>
<div class="hint">📄 To save as PDF: press <strong>Cmd+P</strong> (or Ctrl+P) →
choose <strong>Save as PDF</strong> → Save. This box won't appear in the PDF.</div>
<div class="cover">
  <div class="star">✳</div>
  <div class="cover-title">70 AI Specialists<br/>for Claude</div>
  <p class="tag">Your entire expert team — copywriters, marketers, analysts, closers, coders — in one pack.</p>
  <p class="meta">Copy-paste prompt pack · works in Claude.ai, the API &amp; Claude Code</p>
</div>
""" + "\n".join(body) + "\n</body></html>"

OUT.write_text(html_doc, encoding="utf-8")
print(f"wrote {OUT} ({len(html_doc):,} bytes)")
