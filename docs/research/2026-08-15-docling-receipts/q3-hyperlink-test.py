"""Edge test: does model_dump() stay JSON-serializable on a hyperlink-bearing PDF?

The pr-draft names AnyUrl as the likeliest JSONB serialization failure.
Build a PDF containing a live hyperlink annotation + a URL in text, convert
with the exact call-site idiom, and try json.dumps on default-mode model_dump().
"""

import io
import json
import sys

import fitz  # pymupdf, installed into the venv for this test only

doc = fitz.open()
page = doc.new_page()
page.insert_text((72, 100), "Master Services Agreement", fontsize=18)
page.insert_text((72, 140), "See our terms at https://example.com/terms for details.")
rect = fitz.Rect(72, 160, 300, 180)
page.insert_text((72, 174), "Click here for the data processing addendum")
page.insert_link({"kind": fitz.LINK_URI, "from": rect, "uri": "https://example.com/dpa"})
pdf_bytes = doc.tobytes()
doc.close()

from docling.datamodel.base_models import DocumentStream
from docling.document_converter import DocumentConverter

converter = DocumentConverter()
stream = DocumentStream(name="hyperlink.pdf", stream=io.BytesIO(pdf_bytes))
result = converter.convert(stream)
d = result.document

structured = d.model_dump()
try:
    js = json.dumps(structured)
    print("json_default_mode: ok", len(js), "bytes")
except TypeError as exc:
    print("json_default_mode: FAIL:", exc)
    js = json.dumps(d.model_dump(mode="json"))
    print("json_json_mode: ok", len(js), "bytes")

hyperlinked = [t for t in d.texts if getattr(t, "hyperlink", None)]
print("text items with hyperlink field set:", len(hyperlinked))
for t in hyperlinked:
    print("  hyperlink value:", repr(t.hyperlink), type(t.hyperlink).__name__)
print("DONE")
