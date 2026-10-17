"""Print a reviewable broker entry for one installed bundle; never enable it."""

import argparse
import json
import re
from pathlib import Path

from app.skills.binding import bind_record
from app.skills.loader import load_registry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skill")
    parser.add_argument("--skills-dir", type=Path, required=True)
    parser.add_argument("--community-skills-dir", type=Path)
    parser.add_argument(
        "--image", required=True, help="Reviewed image ID or repository@sha256:digest"
    )
    args = parser.parse_args()
    if not re.fullmatch(r"(?:sha256:[0-9a-f]{64}|[^\s]+@sha256:[0-9a-f]{64})", args.image):
        parser.error("Image must be pinned to an immutable digest")
    record = load_registry(args.skills_dir, args.community_skills_dir).get(args.skill)
    if record is None:
        parser.error("Installed skill was not found")
    binding = bind_record(record)
    if not binding.bundle_digest:
        parser.error("Skill has no declared bundled scripts")
    print(
        json.dumps(
            {
                binding.key: {
                    "image": args.image,
                    "bundle_digest": binding.bundle_digest,
                    "scripts": [script.name for script in binding.capabilities.scripts],
                }
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
