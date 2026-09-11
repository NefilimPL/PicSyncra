"""Unit tests for the local filesystem index cache."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from picsyncra.file_index import INDEX_VERSION, LocalFileIndex
from picsyncra.sqlite_store import SqliteStore


def _index_with_cache(base: Path, generated_at_epoch: float) -> LocalFileIndex:
    root = base / "photos"
    root.mkdir()
    cache_path = base / "file-index.json"
    generated_at = (
        datetime.fromtimestamp(generated_at_epoch, timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )
    cache_path.write_text(
        json.dumps(
            {
                "version": INDEX_VERSION,
                "root": str(root.resolve()),
                "generated_at": generated_at,
                "dirs_scanned": 0,
                "products_scanned": 0,
                "names": [],
                "types": {},
                "models": {},
                "colors": {},
                "extras": {},
                "files": {},
            }
        ),
        encoding="utf-8",
    )
    index = LocalFileIndex(str(root), str(cache_path))
    assert index.load_cache()
    return index


class LocalFileIndexTests(unittest.TestCase):
    def test_refresh_if_stale_skips_fresh_cached_snapshot(self) -> None:
        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            index = _index_with_cache(base, generated_at_epoch=1_000.0)
            started: list[bool] = []
            index.refresh_async = lambda: started.append(True) or True

            self.assertTrue(index.cache_is_fresh(now=1_899.0))
            self.assertFalse(index.refresh_if_stale(now=1_899.0))
            self.assertEqual(started, [])

    def test_refresh_if_stale_starts_for_old_or_forced_snapshot(self) -> None:
        with TemporaryDirectory() as temp_dir:
            index = _index_with_cache(Path(temp_dir), generated_at_epoch=1_000.0)
            started: list[bool] = []
            index.refresh_async = lambda: started.append(True) or True

            self.assertFalse(index.cache_is_fresh(now=1_900.1))
            self.assertTrue(index.refresh_if_stale(now=1_900.1))
            self.assertTrue(index.refresh_if_stale(force=True, now=1_100.0))
            self.assertEqual(started, [True, True])

    def test_refresh_sync_builds_hierarchy_and_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "_ZDJECIA PRZEROBIONE_"
            product_dir = root / "MAGGIORE" / "KOMODA" / "MA03" / "BIALY-CZARNY" / "NO-LED"
            product_dir.mkdir(parents=True)
            (product_dir / "5901234567890_01_MAIN.jpg").write_text("a", encoding="utf-8")
            (product_dir / "5901234567890_02_DETAIL.png").write_text("b", encoding="utf-8")
            alt_dir = root / "MAGGIORE" / "KOMODA" / "MA03" / "BIALY-CZARNY" / "LED-RGB"
            alt_dir.mkdir(parents=True)
            (alt_dir / "5901234567890_08_MOOD.png").write_text("c", encoding="utf-8")
            second_name = root / "LUNA" / "SZAFKA" / "LU01" / "DAB" / "NO-LED"
            second_name.mkdir(parents=True)
            cache_path = base / "file_index.json"

            index = LocalFileIndex(str(root), str(cache_path))
            self.assertFalse(index.load_cache())
            self.assertTrue(index.refresh_sync())

            self.assertEqual(index.get_names(), ["LUNA", "MAGGIORE"])
            self.assertEqual(index.get_types("maggiore"), ["KOMODA"])
            self.assertEqual(index.get_models("MAGGIORE", "komoda"), ["MA03"])
            self.assertEqual(
                index.get_colors("MAGGIORE", "KOMODA", "MA03"),
                ["BIALY-CZARNY"],
            )
            self.assertEqual(
                index.get_extras("MAGGIORE", "KOMODA", "MA03", ["bialy", "czarny"]),
                ["LED-RGB", "NO-LED"],
            )
            self.assertEqual(
                index.get_product_files(
                    "MAGGIORE",
                    "KOMODA",
                    "MA03",
                    ["BIALY", "CZARNY"],
                    "",
                ),
                ["5901234567890_01_MAIN.jpg", "5901234567890_02_DETAIL.png"],
            )
            self.assertEqual(index.get_types("NIE-MA"), None)
            self.assertEqual(index.get_status()["state"], "ready")

    def test_load_cache_reuses_saved_snapshot(self) -> None:
        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "_ZDJECIA PRZEROBIONE_"
            product_dir = root / "MAGGIORE" / "KOMODA" / "MA03" / "BIALY" / "NO-LED"
            product_dir.mkdir(parents=True)
            (product_dir / "5901234567890_01_MAIN.jpg").write_text("a", encoding="utf-8")
            cache_path = base / "file_index.json"

            writer = LocalFileIndex(str(root), str(cache_path))
            self.assertTrue(writer.refresh_sync())

            reader = LocalFileIndex(str(root), str(cache_path))
            self.assertTrue(reader.load_cache())
            self.assertEqual(reader.get_names(), ["MAGGIORE"])
            self.assertEqual(
                reader.get_product_files(
                    "MAGGIORE",
                    "KOMODA",
                    "MA03",
                    ["BIALY"],
                    "NO-LED",
                ),
                ["5901234567890_01_MAIN.jpg"],
            )
            self.assertEqual(reader.get_status()["state"], "cached")

    def test_sqlite_cache_store_reuses_saved_snapshot_without_json_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "_ZDJECIA PRZEROBIONE_"
            product_dir = root / "MAGGIORE" / "KOMODA" / "MA03" / "BIALY" / "NO-LED"
            product_dir.mkdir(parents=True)
            (product_dir / "5901234567890_01_MAIN.jpg").write_text("a", encoding="utf-8")
            cache_path = base / "file_index.json"
            sqlite_store = SqliteStore(str(base / "data.sqlite"))

            writer = LocalFileIndex(
                str(root),
                str(cache_path),
                cache_store=sqlite_store,
            )
            self.assertTrue(writer.refresh_sync())

            self.assertFalse(cache_path.exists())
            self.assertEqual(
                sqlite_store.load_file_index_cache()["names"],
                ["MAGGIORE"],
            )

            reader = LocalFileIndex(
                str(root),
                str(cache_path),
                cache_store=sqlite_store,
            )
            self.assertTrue(reader.load_cache())
            self.assertEqual(reader.get_names(), ["MAGGIORE"])
            self.assertEqual(reader.get_status()["state"], "cached")

    def test_sqlite_cache_store_writes_iso_generated_at_and_segments(self) -> None:
        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "_ZDJECIA PRZEROBIONE_"
            product_dir = root / "MAGGIORE" / "KOMODA" / "MA03" / "BIALY" / "NO-LED"
            product_dir.mkdir(parents=True)
            (product_dir / "5901234567890_01_MAIN.jpg").write_text("a", encoding="utf-8")
            sqlite_store = SqliteStore(str(base / "data.sqlite"))

            index = LocalFileIndex(str(root), str(base / "file_index.json"), cache_store=sqlite_store)
            self.assertTrue(index.refresh_sync())
            snapshot = sqlite_store.load_file_index_cache()

            self.assertIsInstance(snapshot["generated_at"], str)
            self.assertIn("T", snapshot["generated_at"])
            self.assertTrue(snapshot["generated_at"].endswith("Z"))
            self.assertEqual(
                sqlite_store.load_file_index_segment("MAGGIORE", "names", "MAGGIORE"),
                "MAGGIORE",
            )


if __name__ == "__main__":
    unittest.main()
