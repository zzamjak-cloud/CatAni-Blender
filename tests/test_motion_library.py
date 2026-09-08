"""로컬 모션 라이브러리 인덱스와 검색 계약을 검사한다."""

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

from catani.motion_library import assets_from_json, assets_to_json, scan_library, search_assets


class MotionLibraryTests(unittest.TestCase):
    def test_scan_search_and_roundtrip(self):
        with tempfile.TemporaryDirectory(prefix="catani-motion-library-") as directory:
            root = Path(directory)
            (root / "friendly wave.bvh").write_text("HIERARCHY\n", encoding="utf-8")
            (root / "friendly-wave.fbx").write_text("FBX\n", encoding="utf-8")
            (root / "friendly_wave.fbx").write_text("FBX\n", encoding="utf-8")
            (root / "folder.fbx").mkdir()
            (root / "ignore.txt").write_text("skip", encoding="utf-8")
            (root / "motions.json").write_text(json.dumps({
                "motions": [
                    {
                        "file": "friendly wave.bvh",
                        "name": "친근한 손 인사",
                        "tags": ["wave", "greeting", "friendly"],
                        "description": "상대에게 가볍게 인사한다",
                    }
                ]
            }, ensure_ascii=False), encoding="utf-8")

            assets = scan_library(root)
            self.assertEqual(len(assets), 3)
            self.assertEqual(len({asset.identifier for asset in assets}), 3)
            self.assertEqual(assets[0].name, "친근한 손 인사")
            self.assertEqual(assets[0].tags, ("wave", "greeting", "friendly"))

            matches = search_assets(assets, "wave friendly")
            self.assertEqual(len(matches), 3)
            self.assertEqual([asset.name for asset in search_assets(assets, "WAVE\tgreeting")], ["친근한 손 인사"])
            self.assertEqual(search_assets(assets, "인사,가볍게"), [assets[0]])
            self.assertEqual(search_assets(assets, "없는모션"), [])

            restored = assets_from_json(assets_to_json(matches))
            self.assertEqual(restored, matches)

    def test_missing_directory_is_empty(self):
        with tempfile.TemporaryDirectory(prefix="catani-motion-library-") as directory:
            self.assertEqual(scan_library(Path(directory) / "missing"), [])

    def test_empty_directory_and_invalid_manifest(self):
        with tempfile.TemporaryDirectory(prefix="catani-motion-library-") as directory:
            root = Path(directory)
            self.assertEqual(scan_library(root), [])
            manifest = root / "motions.json"
            for value in ([], {"motions": {}}, {"motions": ["wave.bvh"]}, {"motions": [{}]}):
                manifest.write_text(json.dumps(value), encoding="utf-8")
                with self.subTest(value=value), self.assertRaises(ValueError):
                    scan_library(root)
            with self.assertRaises(ValueError):
                scan_library(manifest)

    def test_unicode_names_stable_ids_and_invalid_index(self):
        with tempfile.TemporaryDirectory(prefix="catani-motion-library-") as directory:
            root = Path(directory)
            for name in ("인사.bvh", "걷기.bvh", "nested/wave.BVH"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("인덱스 검사용 합성 자리표시자", encoding="utf-8")
            first = scan_library(root)
            self.assertEqual(len(first), 3)
            self.assertEqual(len({item.identifier for item in first}), 3)
            self.assertEqual(first, scan_library(root))
            self.assertEqual(first, assets_from_json(assets_to_json(first)))
        self.assertEqual(assets_from_json(""), [])
        with self.assertRaises(ValueError):
            assets_from_json("{}")


if __name__ == "__main__":
    unittest.main()
