from pathlib import Path
import sqlite3
import time

from picsyncra import file_index
from picsyncra.file_index import LocalFileIndex
from picsyncra.file_index_segments import DirectoryFingerprint, scan_changed_segments
from picsyncra.services.ftp_listing_cache import RemoteFileRecord, RemoteListingCache
from picsyncra.sqlite_store import SqliteStore


def test_scan_changed_segments_reuses_unchanged_product_directory(tmp_path: Path) -> None:
    root = tmp_path / "files"
    alfa = root / "ALFA"
    beta = root / "BETA"
    alfa.mkdir(parents=True)
    beta.mkdir()
    (alfa / "first.jpg").write_text("alfa", encoding="utf-8")
    (beta / "first.jpg").write_text("beta", encoding="utf-8")

    initial = scan_changed_segments(root, previous_fingerprints={})

    assert initial.full_scan_required is True
    assert initial.changed_segment_keys == ("ALFA", "BETA")

    (beta / "second.jpg").write_text("beta", encoding="utf-8")

    refresh = scan_changed_segments(root, initial.fingerprints)

    assert refresh.full_scan_required is False
    assert refresh.changed_segment_keys == ("BETA",)
    assert refresh.reused_segment_keys == ("ALFA",)


def test_scan_changed_segments_requires_full_scan_for_unreliable_fingerprint(
    tmp_path: Path,
) -> None:
    root = tmp_path / "files"
    product = root / "ALFA"
    product.mkdir(parents=True)
    (product / "first.jpg").write_text("alfa", encoding="utf-8")

    previous = scan_changed_segments(root, previous_fingerprints={})

    def unreliable_fingerprint(path: str, parser_version: int) -> DirectoryFingerprint:
        return DirectoryFingerprint(
            canonical_path=path,
            mtime_ns=0,
            entry_count=0,
            parser_version=parser_version,
            reliable=False,
        )

    refresh = scan_changed_segments(
        root,
        previous.fingerprints,
        fingerprint_provider=unreliable_fingerprint,
    )

    assert refresh.full_scan_required is True
    assert refresh.changed_segment_keys == ("ALFA",)
    assert refresh.reused_segment_keys == ()


def test_refresh_sync_reads_files_only_for_changed_product_segment(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "files"
    alfa_files = root / "ALFA" / "KOMODA" / "A1" / "BIALY" / "NO-LED"
    beta_files = root / "BETA" / "KOMODA" / "B1" / "CZARNY" / "NO-LED"
    alfa_files.mkdir(parents=True)
    beta_files.mkdir(parents=True)
    (alfa_files / "alfa.jpg").write_text("alfa", encoding="utf-8")
    (beta_files / "beta.jpg").write_text("beta", encoding="utf-8")
    index = LocalFileIndex(str(root), str(tmp_path / "file-index.json"))

    assert index.refresh_sync() is True
    (beta_files / "beta-new.jpg").write_text("beta", encoding="utf-8")

    read_paths: list[Path] = []
    original_file_names = file_index._file_names

    def spy_file_names(path: str) -> list[str]:
        read_paths.append(Path(path).resolve())
        return original_file_names(path)

    monkeypatch.setattr(file_index, "_file_names", spy_file_names)

    assert index.refresh_sync() is True

    assert read_paths == [beta_files.resolve()]
    assert index.get_product_files("BETA", "KOMODA", "B1", ["CZARNY"], "") == [
        "beta-new.jpg",
        "beta.jpg",
    ]


def test_refresh_sync_passes_reused_segments_to_cache_store(tmp_path: Path) -> None:
    class RecordingCacheStore:
        def __init__(self) -> None:
            self.reused_segment_keys: list[tuple[str, ...]] = []

        def save_file_index_cache(
            self,
            payload: dict,
            *,
            reused_segment_keys: tuple[str, ...] = (),
        ) -> None:
            self.reused_segment_keys.append(reused_segment_keys)

    root = tmp_path / "files"
    alfa_files = root / "ALFA" / "KOMODA" / "A1" / "BIALY" / "NO-LED"
    beta_files = root / "BETA" / "KOMODA" / "B1" / "CZARNY" / "NO-LED"
    alfa_files.mkdir(parents=True)
    beta_files.mkdir(parents=True)
    (alfa_files / "alfa.jpg").write_text("alfa", encoding="utf-8")
    (beta_files / "beta.jpg").write_text("beta", encoding="utf-8")
    cache_store = RecordingCacheStore()
    index = LocalFileIndex(
        str(root), str(tmp_path / "file-index.json"), cache_store=cache_store
    )

    assert index.refresh_sync() is True
    (beta_files / "beta-new.jpg").write_text("beta", encoding="utf-8")
    assert index.refresh_sync() is True

    assert cache_store.reused_segment_keys == [(), ("ALFA",)]


def test_listing_cache_benchmark_100k_names_reuses_snapshot_after_upload() -> None:
    ftp_config = {
        "host": "ftp.example.test",
        "port": 21,
        "user": "operator",
        "pass": "test-secret",
        "path": "/photos",
    }
    records = [
        RemoteFileRecord(name=f"590{product:010d}_{slot:04d}.jpg")
        for product in range(100)
        for slot in range(1_000)
    ]
    cache = RemoteListingCache(ttl_seconds=60)
    full_listing_calls = 0

    def load_full_listing() -> list[RemoteFileRecord]:
        nonlocal full_listing_calls
        full_listing_calls += 1
        return records

    started_at = time.perf_counter()
    first_snapshot = cache.get_or_refresh(ftp_config, load_full_listing, now=100.0)
    first_lookup_seconds = time.perf_counter() - started_at
    assert len(first_snapshot) == 100_000

    for _ in range(100):
        assert len(cache.get_or_refresh(ftp_config, load_full_listing, now=101.0)) == 100_000

    cache.apply_uploaded(
        ftp_config,
        [RemoteFileRecord(name="5900000000000_1000.jpg")],
    )
    for _ in range(100):
        assert cache.get_if_fresh(ftp_config, now=102.0) is not None

    assert first_lookup_seconds >= 0
    assert full_listing_calls == 1


def test_incremental_index_benchmark_reuses_99_percent_of_segments(tmp_path: Path) -> None:
    root = tmp_path / "products"
    root.mkdir()
    product_names = [f"PRODUCT_{index:05d}" for index in range(10_000)]
    for product_name in product_names:
        (root / product_name).mkdir()

    def fingerprint(path: str, parser_version: int) -> DirectoryFingerprint:
        name = Path(path).name
        index = int(name.rsplit("_", 1)[1])
        return DirectoryFingerprint(
            canonical_path=path,
            mtime_ns=2 if index % 100 == 0 else 1,
            entry_count=0,
            parser_version=parser_version,
        )

    baseline = scan_changed_segments(
        root,
        previous_fingerprints={},
        fingerprint_provider=lambda path, version: DirectoryFingerprint(
            canonical_path=path,
            mtime_ns=1,
            entry_count=0,
            parser_version=version,
        ),
    )
    refresh = scan_changed_segments(
        root,
        previous_fingerprints=baseline.fingerprints,
        fingerprint_provider=fingerprint,
    )

    assert refresh.segments_scanned == 100
    assert refresh.segments_reused == 9_900

    store = SqliteStore(str(tmp_path / "data.sqlite"))
    initial_snapshot = {
        "version": 1,
        "root": str(root),
        "generated_at": "2026-08-06T10:00:00.000Z",
        "names": product_names,
        "types": {name: ["TYPE"] for name in product_names},
        "models": {},
        "colors": {},
        "extras": {},
        "files": {},
    }
    store.save_file_index_cache(initial_snapshot)
    changed_segment_keys = set(refresh.changed_segment_keys)
    updated_snapshot = {
        **initial_snapshot,
        "generated_at": "2026-08-06T10:01:00.000Z",
        "types": {
            name: ["TYPE", "CHANGED"] if name in changed_segment_keys else ["TYPE"]
            for name in product_names
        },
    }
    store.save_file_index_cache(
        updated_snapshot,
        reused_segment_keys=refresh.reused_segment_keys,
    )

    with sqlite3.connect(tmp_path / "data.sqlite") as connection:
        active_generations = connection.execute(
            "SELECT COUNT(*) FROM file_index_generations WHERE complete = 1"
        ).fetchone()[0]
    assert active_generations == 1
