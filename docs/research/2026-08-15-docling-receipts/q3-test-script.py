"""Q3 gate-1 test: replicate api/app/pipeline/parsers.py::_run_docling against Docling 2.x.

Runs the EXACT call-site idiom (DocumentStream(name=..., stream=BytesIO),
converter.convert(stream), result.document, doc.model_dump()) on real repo
sample contracts, then checks JSON-serializability (the AnyUrl concern),
round-trip deserialization (the M2-reader concern), and structure quality
metrics (tables, headings, labels).
"""

import io
import json
import sys
import time
import traceback
import importlib.metadata
from collections import Counter
from pathlib import Path

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
pdf_paths = sys.argv[2:]

from docling.datamodel.base_models import DocumentStream
from docling.document_converter import DocumentConverter

results = []
converter = DocumentConverter()

for p in pdf_paths:
    rec = {"file": Path(p).name}
    try:
        pdf_bytes = Path(p).read_bytes()
        t0 = time.time()
        # --- exact call-site idiom from parsers.py:_run_docling ---
        stream = DocumentStream(name=Path(p).name, stream=io.BytesIO(pdf_bytes))
        result = converter.convert(stream)
        doc = getattr(result, "document", None) or getattr(result, "output", None)
        if doc is None:
            raise RuntimeError("Docling returned no document on conversion result")
        structured = doc.model_dump() if hasattr(doc, "model_dump") else {"raw": str(doc)}
        # -----------------------------------------------------------
        rec["convert_seconds"] = round(time.time() - t0, 2)
        rec["conversion_status"] = str(getattr(result, "status", None))

        # JSON-serializability of model_dump() output — the candidate failure
        # named in the brief (AnyUrl and similar non-JSON-native types).
        try:
            js = json.dumps(structured)
            rec["json_default_mode"] = "ok"
            rec["json_payload_bytes"] = len(js)
        except TypeError as exc:
            rec["json_default_mode"] = f"FAIL: {exc}"
            js = json.dumps(doc.model_dump(mode="json"))
            rec["json_json_mode"] = "ok"
            rec["json_payload_bytes"] = len(js)

        # Round-trip: can an M2 reader deserialize the stored payload back
        # into a DoclingDocument?
        try:
            from docling_core.types.doc import DoclingDocument
            DoclingDocument.model_validate(json.loads(js))
            rec["roundtrip"] = "ok"
        except Exception as exc:
            rec["roundtrip"] = f"FAIL: {type(exc).__name__}: {exc}"

        # Structure quality metrics.
        rec["num_tables"] = len(getattr(doc, "tables", []) or [])
        rec["num_pictures"] = len(getattr(doc, "pictures", []) or [])
        texts = getattr(doc, "texts", []) or []
        rec["num_text_items"] = len(texts)
        rec["text_labels"] = dict(Counter(str(getattr(t, "label", "?")) for t in texts))

        # Table cell counts, to judge whether table extraction found real cells.
        tables_info = []
        for t in getattr(doc, "tables", []) or []:
            try:
                data = t.data
                tables_info.append({
                    "num_rows": getattr(data, "num_rows", None),
                    "num_cols": getattr(data, "num_cols", None),
                    "num_cells": len(getattr(data, "table_cells", []) or []),
                })
            except Exception as exc:
                tables_info.append({"error": str(exc)})
        rec["tables"] = tables_info

        md = doc.export_to_markdown()
        (OUT / (Path(p).stem + ".docling.md")).write_text(md)
        rec["markdown_chars"] = len(md)
        rec["ok"] = True
    except Exception:
        rec["ok"] = False
        rec["traceback"] = traceback.format_exc()
    results.append(rec)
    print(json.dumps({k: v for k, v in rec.items() if k != "traceback"}), flush=True)
    if not rec["ok"]:
        print(rec["traceback"], flush=True)

meta = {}
for pkg in ("docling", "docling-core", "docling-parse", "docling-ibm-models", "torch"):
    try:
        meta[pkg] = importlib.metadata.version(pkg)
    except Exception:
        meta[pkg] = "not-installed"

(OUT / "summary.json").write_text(json.dumps({"meta": meta, "results": results}, indent=2))
print("ALL_DONE", json.dumps(meta))
