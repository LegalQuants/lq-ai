"""Bundled demonstration helper. Input text is data, never evaluated."""

import json
import sys

inputs = json.load(sys.stdin)
if set(inputs) != {"text"} or not isinstance(inputs["text"], str):
    print("Expected one text field", file=sys.stderr)
    sys.exit(2)
text = inputs["text"]
print(json.dumps({
    "line_count": len(text.splitlines()),
    "word_count": len(text.split()),
    "preview": text[:200],
}, ensure_ascii=False))
