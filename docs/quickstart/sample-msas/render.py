"""Render the 5 synthetic MSA markdown files to PDF via Chrome headless.

Mirrors `docs/quickstart/sample-ndas/render.py` exactly so a single
"regenerate the synthetic corpus" pass can be run against either
directory by `cd`-ing into it first.
"""

import os
import pathlib
import subprocess
import sys

import markdown as md

HERE = pathlib.Path(__file__).resolve().parent

CSS = """
@page { size: Letter; margin: 1in 1in 1in 1in; }
body {
  font-family: 'Georgia', 'Times New Roman', Times, serif;
  font-size: 11pt;
  line-height: 1.45;
  color: #111;
}
h1 { font-size: 16pt; text-align: center; margin: 0 0 16pt; font-weight: 700; }
h2 { font-size: 12pt; margin: 18pt 0 6pt; font-weight: 700; }
p { margin: 6pt 0; text-align: justify; }
strong { font-weight: 700; }
table { width: 100%; border-collapse: collapse; margin: 18pt 0 6pt; }
td, th { vertical-align: top; padding: 6pt 10pt; font-size: 11pt; border: 1px solid #ccc; }
ul, ol { margin: 6pt 0; padding-left: 22pt; }
li { margin: 2pt 0; }
"""

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def render_one(md_path: pathlib.Path) -> pathlib.Path:
    html_body = md.markdown(
        md_path.read_text(),
        extensions=["tables", "extra"],
    )
    html_doc = f"""<!doctype html>
<html><head><meta charset="utf-8"><style>{CSS}</style></head>
<body>{html_body}</body></html>
"""
    html_path = md_path.with_suffix(".html")
    html_path.write_text(html_doc)
    pdf_path = md_path.with_suffix(".pdf")
    cmd = [
        CHROME,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        f"--print-to-pdf={pdf_path}",
        "--no-pdf-header-footer",
        f"file://{html_path}",
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    html_path.unlink()
    return pdf_path


def main() -> int:
    if not pathlib.Path(CHROME).exists():
        print(f"Chrome not found at {CHROME}", file=sys.stderr)
        return 1
    md_files = sorted(HERE.glob("msa-*.md"))
    if not md_files:
        print("No msa-*.md files found.", file=sys.stderr)
        return 1
    for md_path in md_files:
        pdf_path = render_one(md_path)
        size_kb = os.path.getsize(pdf_path) / 1024
        print(f"  {pdf_path.name} ({size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
