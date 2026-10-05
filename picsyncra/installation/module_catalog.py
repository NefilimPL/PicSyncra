"""Catalog signed module releases, retaining explicit unavailable entries."""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from .module_contracts import ModuleRelease
from .module_manifest import verify_module_manifest
from .release_manifest import ManifestError


@dataclass(frozen=True)
class ModuleCatalogEntry:
    release_id: int
    tag: str
    published_at: str
    release: ModuleRelease | None
    blocked_reason: str | None = None


def catalog_module_releases(records: Sequence[object], *, channel: str, manifest_loader,
                            trusted_keys: Mapping[str, bytes | str]) -> tuple[ModuleCatalogEntry, ...]:
    if channel not in {'stable', 'dev'}:
        raise ValueError('Invalid module channel.')
    candidates = [record for record in records if isinstance(record, dict)
                  and type(record.get('id')) is int and record['id'] > 0
                  and isinstance(record.get('tag_name'), str)
                  and record.get('draft') is False and record.get('prerelease') is (channel == 'dev')]
    by_id = {record['id']: record for record in candidates}
    result = []
    for record in sorted(candidates, key=lambda item: str(item.get('published_at', '')), reverse=True):
        release = None
        reason = None
        try:
            raw, signature, key_id = manifest_loader(record)
            release = verify_module_manifest(raw, signature, trusted_keys, key_id=key_id)
            if release.release_id != record['id'] or release.tag != record['tag_name'] or release.channel != channel:
                raise ManifestError('Release provenance mismatch.')
        except (ManifestError, OSError, ValueError, TypeError):
            reason = 'manifest_unavailable'
        if release is not None and reason is None:
            for module in release.modules:
                source = by_id.get(module.source_release_id)
                if source is None or source['tag_name'] != module.source_tag:
                    reason = 'source_release_unavailable'
                    break
                assets = {asset.get('name'): asset for asset in source.get('assets', []) if isinstance(asset, dict)}
                if any(file.asset_name not in assets or type(assets[file.asset_name].get('size')) is not int
                       or assets[file.asset_name]['size'] != file.asset_size for file in module.files):
                    reason = 'content_unavailable'
                    break
        result.append(ModuleCatalogEntry(record['id'], record['tag_name'], str(record.get('published_at', '')), release, reason))
    return tuple(result)
