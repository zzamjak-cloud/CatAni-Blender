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

    def test_newest_release_only(self):
        """id마다 항목이 하나여야 하므로 가장 높은 버전만 골라야 한다."""
        def release(tag):
            return {"tag_name": tag, "draft": False, "prerelease": False,
                    "assets": [{"name": f"catani-{tag}.zip"}, {"name": f"catani-{tag}.zip.sha256"}]}
        with patch.object(repository, "request_json", side_effect=[
            [release("v0.5.0"), release("v0.5.1"), release("v0.4.9")],
            [release("v0.10.0"), release("v0.9.12")], [],
        ]):
            latest = repository.newest_release("owner/repo")
        self.assertIsNotNone(latest)
        self.assertEqual(latest[0], "v0.10.0", "숫자 정렬이 아니라 문자열 정렬로 골랐습니다")

        with patch.object(repository, "request_json", return_value=[]):
            self.assertIsNone(repository.newest_release("owner/repo"))

    def test_index_holds_one_entry_per_id_and_verifies_hash(self):
        name = "catani-v0.5.1.zip"
        assets = {name: {"url": f"https://github.com/o/r/releases/download/v0.5.1/{name}", "sha256": "1" * 64}}
        index = {"version": "v1", "blocklist": [], "data": [
            {"id": "catani", "archive_url": "./" + name, "archive_hash": "sha256:" + "1" * 64}]}
        original = json.loads(json.dumps(index))
        result = repository.rewrite_index(index, assets)
        self.assertEqual(len(result["data"]), 1)
        self.assertEqual(result["data"][0]["archive_url"], assets[name]["url"])

        # 같은 id가 두 번 들어가면 Blender가 마지막 항목을 설치 대상으로 잡는다.
        both = {version: {"url": f"https://github.com/o/r/releases/download/v{version}/catani-v{version}.zip",
                          "sha256": "1" * 64} for version in ("0.5.0", "0.5.1")}
        duplicated = {f"catani-v{version}.zip": value for version, value in both.items()}
        with self.assertRaisesRegex(RuntimeError, "같은 id가 여러 번"):
            repository.rewrite_index({"version": "v1", "data": [
                {"id": "catani", "archive_url": "./" + key, "archive_hash": "sha256:" + "1" * 64}
                for key in duplicated]}, duplicated)

        original["data"][0]["archive_hash"] = "sha256:incorrect"
        with self.assertRaisesRegex(RuntimeError, "무결성 불일치"):
            repository.rewrite_index(original, assets)
        with self.assertRaisesRegex(RuntimeError, "누락"):
            repository.rewrite_index({"data": []}, assets)


if __name__ == "__main__":
    unittest.main()
