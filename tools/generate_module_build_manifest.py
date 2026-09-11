from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from picsyncra.services.module_build_status import build_manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate embedded PicSyncra module build metadata."
    )
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--build-variant", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    manifest = build_manifest(
        args.repo_root.resolve(),
        build_variant=args.build_variant,
        now=datetime.now(UTC),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
