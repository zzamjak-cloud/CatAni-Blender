"""로컬 파일과 공개 카탈로그를 합친 모션 목록·검색 계약을 검사한다."""

import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

root = Path(__file__).resolve().parents[1]
package = types.ModuleType("catani")
package.__path__ = [str(root / "catani")]
sys.modules["catani"] = package

from catani.motion_library import browse, catalog_assets, make_asset, scan_library, search_assets
from catani.source_catalog import CATALOG


class MotionLibraryTests(unittest.TestCase):
    def test_scan_reads_manifest_and_search_narrows(self):
        with tempfile.TemporaryDirectory(prefix="catani-motion-library-") as directory:
            library = Path(directory)
            (library / "friendly wave.bvh").write_text("HIERARCHY\n", encoding="utf-8")
            (library / "friendly-wave.fbx").write_text("FBX\n", encoding="utf-8")
            (library / "friendly_wave.fbx").write_text("FBX\n", encoding="utf-8")
            (library / "folder.fbx").mkdir()
            (library / "ignore.txt").write_text("skip", encoding="utf-8")
            (library / "motions.json").write_text(json.dumps({
                "motions": [{
                    "file": "friendly wave.bvh",
                    "name": "친근한 손 인사",
                    "tags": ["wave", "greeting", "friendly"],
                    "description": "상대에게 가볍게 인사한다",
                }]
            }, ensure_ascii=False), encoding="utf-8")

            assets = scan_library(library)
            self.assertEqual(len(assets), 3)
            self.assertEqual(len({asset.identifier for asset in assets}), 3)
            named = next(asset for asset in assets if asset.name == "친근한 손 인사")
            self.assertEqual(named.tags, ("wave", "greeting", "friendly"))
            self.assertTrue(named.available)
            self.assertGreater(named.size_bytes, 0)

            self.assertEqual(len(search_assets(assets, "wave friendly")), 3)
            self.assertEqual([a.name for a in search_assets(assets, "WAVE\tgreeting")], ["친근한 손 인사"])
            self.assertEqual(search_assets(assets, "인사,가볍게"), [named])
            self.assertEqual(search_assets(assets, "없는모션"), [])

    def test_manifest_records_download_origin(self):
        entry = CATALOG[0]
        with tempfile.TemporaryDirectory(prefix="catani-motion-origin-") as directory:
            library = Path(directory)
            target = library / entry.local_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("HIERARCHY\n", encoding="utf-8")
            (library / "motions.json").write_text(json.dumps({"motions": [{
                "file": entry.local_path, "name": entry.name, "tags": list(entry.tags),
                "download_url": entry.download_url, "sha256": entry.sha256,
                "source_name": entry.source_name, "license_note": entry.license_note,
            }]}, ensure_ascii=False), encoding="utf-8")
            asset = scan_library(library)[0]
            self.assertEqual(asset.download_url, entry.download_url)
            self.assertEqual(asset.sha256, entry.sha256)
            self.assertEqual(asset.source_id, entry.id, "받아 둔 파일이 카탈로그 항목과 이어지지 않았습니다")

    def test_browse_offers_catalog_until_downloaded(self):
        with tempfile.TemporaryDirectory(prefix="catani-motion-browse-") as directory:
            library = Path(directory)
            listed = browse(library)
            self.assertEqual(len(listed), len(CATALOG))
            self.assertTrue(all(not asset.available and asset.source_id for asset in listed))
            self.assertTrue(all(asset.size_bytes > 0 for asset in listed))

            entry = CATALOG[0]
            target = library / entry.local_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("HIERARCHY\n", encoding="utf-8")
            after = browse(library)
            self.assertEqual(len(after), len(CATALOG))
            self.assertEqual(sum(1 for asset in after if asset.available), 1)
            self.assertEqual([asset.source_id for asset in catalog_assets(library)].count(entry.id), 0)
            self.assertEqual(len(browse(library, "없는검색어")), 0)
            self.assertEqual(len(browse("", "")), len(CATALOG), "폴더가 비어 있어도 공개 카탈로그는 보여야 합니다")

    def test_browse_filters_by_category_and_local_only(self):
        with tempfile.TemporaryDirectory(prefix="catani-motion-filter-") as directory:
            library = Path(directory)
            entry = CATALOG[0]
            self.assertTrue(entry.category, "검사에 쓸 카탈로그 항목에 카테고리가 없습니다")
            same = [item for item in CATALOG if item.category == entry.category]
            listed = browse(library, category=entry.category)
            self.assertEqual(len(listed), len(same))
            self.assertTrue(all(asset.category == entry.category for asset in listed))
            self.assertEqual(browse(library, local_only=True), [])

            target = library / entry.local_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("HIERARCHY\n", encoding="utf-8")
            (library / "motions.json").write_text(
                json.dumps({"motions": [{"file": entry.local_path, "name": entry.name, "download_url": entry.download_url}]}),
                encoding="utf-8")
            local = browse(library, local_only=True)
            self.assertEqual(len(local), 1)
            # 받아 둔 파일도 출처를 통해 카테고리를 이어받아 같은 필터에 걸린다.
            self.assertEqual(local[0].category, entry.category)
            self.assertEqual(len(browse(library, category=entry.category, local_only=True)), 1)

    def test_missing_directory_and_invalid_manifest(self):
        with tempfile.TemporaryDirectory(prefix="catani-motion-library-") as directory:
            library = Path(directory)
            self.assertEqual(scan_library(library / "missing"), [])
            self.assertEqual(scan_library(library), [])
            manifest = library / "motions.json"
            for value in ([], {"motions": {}}, {"motions": ["wave.bvh"]}, {"motions": [{}]},
                          {"motions": [{"file": "a.bvh", "sha256": 1}]}):
                manifest.write_text(json.dumps(value), encoding="utf-8")
                with self.subTest(value=value), self.assertRaises(ValueError):
                    scan_library(library)
            with self.assertRaises(ValueError):
                scan_library(manifest)

    def test_unicode_names_and_stable_ids(self):
        with tempfile.TemporaryDirectory(prefix="catani-motion-library-") as directory:
            library = Path(directory)
            for name in ("인사.bvh", "걷기.bvh", "nested/wave.BVH"):
                path = library / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("인덱스 검사용 합성 자리표시자", encoding="utf-8")
            first = scan_library(library)
            self.assertEqual(len(first), 3)
            self.assertEqual(len({item.identifier for item in first}), 3)
            self.assertEqual(first, scan_library(library))
            (library / "skip.gltf").write_text("no", encoding="utf-8")
            with self.assertRaises(ValueError):
                make_asset(library / "skip.gltf")
            with self.assertRaises(ValueError):
                make_asset(library / "없는파일.bvh")


if __name__ == "__main__":
    unittest.main()
