"""원격 저장소의 릴리스 필터와 무결성 실패 경로를 검사한다."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import build_repository as repository


class DistributionTests(unittest.TestCase):
    def test_release_pagination_and_filter(self):
        def release(tag, draft=False, prerelease=False):
            return {"tag_name": tag, "draft": draft, "prerelease": prerelease,
                    "assets": [{"name": f"catani-{tag}.zip"}, {"name": f"catani-{tag}.zip.sha256"}]}
        with patch.object(repository, "request_json", side_effect=[
            [release("v0.2.0"), release("v0.2.1", draft=True), release("v0.3.0", prerelease=True)],
            [release("v0.2.2")], [],
        ]) as request:
            assets = list(repository.published_assets("owner/repo"))
        self.assertEqual([asset[0] for asset in assets], ["v0.2.0", "v0.2.2"])
        self.assertIn("page=3", request.call_args.args[0])

    def test_missing_checksum_is_rejected(self):
        release = {"tag_name": "v0.2.1", "draft": False, "prerelease": False,
                   "assets": [{"name": "catani-v0.2.1.zip"}]}
        with patch.object(repository, "request_json", return_value=[release]):
            with self.assertRaisesRegex(RuntimeError, "체크섬 누락"):
                list(repository.published_assets("owner/repo"))

    def test_archive_hash_and_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catani-v0.2.1.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("blender_manifest.toml", 'id = "catani"\nversion = "0.2.1"\n')
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            checksum = f"{digest}  {path.name}\n"
            self.assertEqual(repository.validate_archive(path, "0.2.1", checksum), digest)
            with self.assertRaisesRegex(RuntimeError, "매니페스트 불일치"):
                repository.validate_archive(path, "0.2.2", checksum)
            with self.assertRaisesRegex(RuntimeError, "SHA256 불일치"):
                repository.validate_archive(path, "0.2.1", f"{'0' * 64}  {path.name}")

    def test_index_preserves_all_versions_and_verifies_hash(self):
        assets = {f"catani-v{version}.zip": {"url": f"https://github.com/o/r/releases/download/v{version}/catani-v{version}.zip", "sha256": "1" * 64}
                  for version in ("0.2.0", "0.2.1")}
        index = {"version": "v1", "blocklist": [], "data": [
            {"id": "catani", "archive_url": "./" + name, "archive_hash": "sha256:" + asset["sha256"]}
            for name, asset in assets.items()]}
        original = json.loads(json.dumps(index))
        result = repository.rewrite_index(index, assets)
        self.assertEqual(len(result["data"]), 2)
        self.assertTrue(all(item["archive_url"].startswith("https://github.com/") for item in result["data"]))
        original["data"][0]["archive_hash"] = "sha256:incorrect"
        with self.assertRaisesRegex(RuntimeError, "무결성 불일치"):
            repository.rewrite_index(original, assets)
        with self.assertRaisesRegex(RuntimeError, "누락"):
            repository.rewrite_index({"data": []}, assets)


if __name__ == "__main__":
    unittest.main()
