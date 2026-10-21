"""Generate the unsigned, schema-1 manifest for an installed release."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def generate_manifest(*, release_id: int, tag: str, commit: str, channel: str, source_branch: str, prerelease: bool, minimum_controller: int, components: list[tuple[str, str, Path]]) -> dict[str, object]:
    if channel not in {"stable", "dev"} or (channel == "stable" and (prerelease or source_branch != "main")) or (channel == "dev" and not prerelease):
        raise ValueError("channel metadata is inconsistent")
    if release_id <= 0 or minimum_controller <= 0 or len(commit) != 40:
        raise ValueError("release metadata is invalid")
    entries = []
    for name, component_id, path in components:
        source = Path(path)
        if name not in {"web", "migrator", "local", "ocr"} or not source.is_file() or source.name != str(source.name):
            raise ValueError("component is invalid")
        entries.append({"name": name, "component_id": component_id, "asset_name": source.name, "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "size": source.stat().st_size})
    if {entry["name"] for entry in entries} < {"web", "migrator"}:
        raise ValueError("web and migrator are required")
    return {"schema": 1, "release_id": release_id, "tag": tag, "commit": commit.lower(), "channel": channel, "source_branch": source_branch, "prerelease": prerelease, "platform": "windows-x64", "minimum_controller": minimum_controller, "components": entries}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-id", type=int, required=True); parser.add_argument("--tag", required=True); parser.add_argument("--commit", required=True)
    parser.add_argument("--channel", choices=("stable", "dev"), required=True); parser.add_argument("--source-branch", required=True)
    parser.add_argument("--prerelease", action="store_true"); parser.add_argument("--minimum-controller", type=int, default=1); parser.add_argument("--component", action="append", required=True); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    components = []
    for value in args.component:
        try: name, component_id, raw_path = value.split(":", 2)
        except ValueError as exc: raise SystemExit("--component must be name:component_id:path") from exc
        components.append((name, component_id, Path(raw_path)))
    manifest = generate_manifest(release_id=args.release_id, tag=args.tag, commit=args.commit, channel=args.channel, source_branch=args.source_branch, prerelease=args.prerelease, minimum_controller=args.minimum_controller, components=components)
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return 0


if __name__ == "__main__": raise SystemExit(main())
