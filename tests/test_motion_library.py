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

from catani.motion_library import (MotionAsset, browse, catalog_assets, filter_assets, make_asset, merge_manifest,
                                   read_manifest, scan_library, search_assets, update_manifest)
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

    def test_filter_hides_noncommercial(self):
        """비상업 라이선스 출처는 기본 목록에서 빠져야 한다."""
        free = MotionAsset(identifier="a", name="자유", path="", file_type="bvh", category="walk")
        limited = MotionAsset(identifier="b", name="비상업", path="", file_type="bvh",
                              category="walk", commercial_use=False)
        self.assertEqual([a.name for a in filter_assets([free, limited])], ["자유", "비상업"])
        self.assertEqual([a.name for a in filter_assets([free, limited], commercial_only=True)], ["자유"])
        self.assertEqual([a.name for a in filter_assets([free, limited], category="walk", commercial_only=True)], ["자유"])
        self.assertEqual(filter_assets([limited], commercial_only=True), [])

    def test_search_finds_file_name_after_rename(self):
        """이름을 바꿔도 원본 파일 이름으로 찾을 수 있어야 한다."""
        entry = CATALOG[0]
        with tempfile.TemporaryDirectory(prefix="catani-motion-search-") as directory:
            library = Path(directory)
            target = library / entry.local_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("HIERARCHY\nMOTION\n", encoding="utf-8")
            update_manifest(library, entry.local_path, {"name": "내가 고른 자세", "tags": []})
            assets = scan_library(library)
            self.assertEqual([a.name for a in search_assets(assets, "내가 자세")], ["내가 고른 자세"])
            self.assertEqual([a.name for a in search_assets(assets, target.stem)], ["내가 고른 자세"])
            self.assertEqual(search_assets(assets, "없는이름"), [])

    def test_catalog_name_survives_missing_manifest(self):
        """예전 버전이 받아 둔 파일은 motions.json이 없어도 카탈로그 이름으로 보여야 한다."""
        entry = CATALOG[0]
        with tempfile.TemporaryDirectory(prefix="catani-motion-recover-") as directory:
            library = Path(directory)
            target = library / entry.local_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("HIERARCHY\nMOTION\n", encoding="utf-8")
            asset = scan_library(library)[0]
            self.assertEqual(asset.name, entry.name)
            self.assertEqual(asset.source_id, entry.id)
            self.assertEqual(asset.category, entry.category)
            self.assertEqual(asset.download_url, entry.download_url)
            self.assertEqual(asset.blob_sha1, entry.blob_sha1)
            self.assertEqual(asset.tags, tuple(entry.tags))
            # 파일 이름만 남은 표시(`49 09`)로 떨어지지 않는다.
            self.assertNotEqual(asset.name, target.stem.replace("_", " "))

    def test_manual_rename_persists_and_wins(self):
        """손으로 바꾼 이름은 motions.json에 남고 카탈로그 이름을 덮는다."""
        entry = CATALOG[0]
        with tempfile.TemporaryDirectory(prefix="catani-motion-rename-") as directory:
            library = Path(directory)
            target = library / entry.local_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("HIERARCHY\nMOTION\n", encoding="utf-8")
            update_manifest(library, entry.local_path, {"name": "발레 1번 · 팔 올리기"})
            asset = scan_library(library)[0]
            self.assertEqual(asset.name, "발레 1번 · 팔 올리기")
            # 이름만 바꿨어도 출처와 체크섬은 카탈로그에서 그대로 이어받는다.
            self.assertEqual(asset.source_id, entry.id)
            self.assertEqual(asset.blob_sha1, entry.blob_sha1)
            # 두 번째 변경은 기존 항목을 늘리지 않고 갱신한다.
            update_manifest(library, entry.local_path, {"name": "발레 시작 자세"})
            manifest = read_manifest(library)
            self.assertEqual(len(manifest), 1)
            self.assertEqual(manifest[entry.local_path]["name"], "발레 시작 자세")
            self.assertEqual(scan_library(library)[0].name, "발레 시작 자세")
            self.assertNotIn(".catani-index-", " ".join(p.name for p in library.iterdir()))
            with self.assertRaises(ValueError):
                update_manifest(library, "../탈출.bvh", {"name": "안 됨"})
            with self.assertRaises(ValueError):
                update_manifest(library / "없는폴더", entry.local_path, {"name": "안 됨"})

    def test_merge_manifest_folds_many_entries_at_once(self):
        """폴더를 통째로 가져올 때 인덱스를 한 번만 쓰고 기존 이름은 지키는지."""
        entries = CATALOG[:3]
        with tempfile.TemporaryDirectory(prefix="catani-motion-merge-") as directory:
            library = Path(directory)
            for entry in entries:
                target = library / entry.local_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("HIERARCHY\nMOTION\n", encoding="utf-8")
            update_manifest(library, entries[0].local_path, {"name": "먼저 붙인 이름", "description": "지켜야 한다"})
            merged = merge_manifest(library, {entry.local_path: {"name": f"가져온 {index}"}
                                              for index, entry in enumerate(entries)})
            self.assertEqual(len(merged), len(entries))
            manifest = read_manifest(library)
            self.assertEqual(len(manifest), len(entries))
            # 같은 파일의 기존 필드는 남고 넘긴 필드만 덮인다.
            self.assertEqual(manifest[entries[0].local_path]["description"], "지켜야 한다")
            self.assertEqual(manifest[entries[0].local_path]["name"], "가져온 0")
            self.assertEqual({asset.name for asset in scan_library(library)},
                             {f"가져온 {index}" for index in range(len(entries))})
            self.assertNotIn(".catani-index-", " ".join(path.name for path in library.iterdir()))
            with self.assertRaises(ValueError):
                merge_manifest(library, {"../탈출.bvh": {"name": "안 됨"}})

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
