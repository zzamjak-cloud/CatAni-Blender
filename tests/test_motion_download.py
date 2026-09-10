"""실제 네트워크 없이 카탈로그 메타데이터와 다운로드·인덱싱을 검사한다."""

from dataclasses import replace
import hashlib
import io
import zipfile
import importlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

from motion_download_fixture import BVH_BYTES, MemoryResponse

root = Path(__file__).resolve().parents[1]
package = types.ModuleType("catani")
package.__path__ = [str(root / "catani")]
sys.modules["catani"] = package
catalog = importlib.import_module("catani.source_catalog")
downloader = importlib.import_module("catani.motion_downloader")
library = importlib.import_module("catani.motion_library")


class MotionDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="catani-download-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.entry = replace(catalog.CATALOG[0], sha256=hashlib.sha256(BVH_BYTES).hexdigest(),
                             blob_sha1=downloader.git_blob_sha1(BVH_BYTES), size_bytes=len(BVH_BYTES))
        self.requests = []
        forbidden_network = patch.object(downloader, "urlopen", side_effect=AssertionError("기본 회귀 검사에서 실제 네트워크 호출 금지"))
        forbidden_network.start()
        self.addCleanup(forbidden_network.stop)

    def opener(self, request, timeout=None):
        self.requests.append(request.full_url)
        return MemoryResponse()

    def test_catalog_exposes_source_license_and_verifiable_downloads(self):
        self.assertGreaterEqual(len(catalog.CATALOG), 300, "카탈로그가 충분히 넓지 않습니다")
        self.assertGreaterEqual(len({entry.category for entry in catalog.CATALOG}), 20, "동작 분류가 부족합니다")
        self.assertEqual(len({entry.local_path for entry in catalog.CATALOG}), len(catalog.CATALOG))
        self.assertEqual(len({entry.id for entry in catalog.CATALOG}), len(catalog.CATALOG))
        for entry in catalog.CATALOG:
            with self.subTest(source=entry.id):
                self.assertTrue(entry.name and entry.tags and entry.source_name and entry.license_note)
                for url in (entry.source_url, entry.license_url, entry.download_url):
                    parsed = urlparse(url)
                    self.assertIn(parsed.scheme, ("http", "https"))
                    self.assertTrue(parsed.hostname)
                    self.assertNotIn(parsed.hostname, ("example.com", "localhost"))
                # 고정 리비전의 git blob 해시나 SHA-256 중 하나 이상으로 검증할 수 있어야 한다.
                self.assertTrue(entry.blob_sha1 or entry.sha256, "검증 가능한 체크섬이 없습니다")
                if entry.blob_sha1:
                    self.assertRegex(entry.blob_sha1, r"^[0-9a-f]{40}$")
                if entry.sha256:
                    self.assertRegex(entry.sha256, r"^[0-9a-f]{64}$")
                self.assertGreater(entry.size_bytes, 0)
                self.assertLessEqual(entry.size_bytes, catalog.MAX_FILE_BYTES)
                self.assertIn(urlparse(entry.download_url).hostname, catalog.ALLOWED_HOSTS)
                self.assertEqual(Path(entry.local_path).suffix.lower(), ".bvh")
                self.assertFalse(Path(entry.local_path).is_absolute())
                self.assertNotIn("..", Path(entry.local_path).parts)
                self.assertEqual(catalog.get_source(entry.id), entry)

    def _archive(self, members):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, data in members.items():
                archive.writestr(name, data)
        return buffer.getvalue()

    def _archive_pair(self):
        """같은 ZIP에서 나오는 두 항목과 그 ZIP 바이트."""
        first, second = BVH_BYTES, BVH_BYTES + b"0 0 0 9 0 0\n"
        payload = self._archive({
            "A_Walk.bvh": first, "A_Run.bvh": second,
            "../escape.bvh": BVH_BYTES, "notes.txt": b"skip me",
        })
        url = "https://accad.osu.edu/sites/accad.osu.edu/files/T_bvh.zip"
        left = replace(catalog.CATALOG[0], id="t_walk", name="검사 걷기", local_path="ACCAD/A_Walk.bvh",
                       download_url=url, archive_member="A_Walk.bvh", blob_sha1="",
                       size_bytes=len(first), sha256=hashlib.sha256(first).hexdigest(),
                       archive_sha256=hashlib.sha256(payload).hexdigest(), archive_size_bytes=len(payload))
        right = replace(left, id="t_run", name="검사 달리기", local_path="ACCAD/A_Run.bvh",
                        archive_member="A_Run.bvh", size_bytes=len(second),
                        sha256=hashlib.sha256(second).hexdigest())
        return payload, left, right

    def test_archive_download_extracts_every_member_once(self):
        """ZIP 배포본은 한 번 받아 안의 BVH를 모두 풀고 등록해야 한다."""
        payload, left, right = self._archive_pair()
        with patch.object(downloader, "entries_in_archive", lambda url: (left, right)), \
             patch.object(downloader, "urlopen", lambda request, timeout=None: (
                 self.requests.append(request.full_url), MemoryResponse(payload))[1]):
            path = downloader.download_asset(left, self.directory)
        self.assertEqual(path, (self.directory / "ACCAD/A_Walk.bvh").resolve())
        self.assertTrue((self.directory / "ACCAD/A_Run.bvh").is_file(), "같은 묶음의 다른 항목이 풀리지 않았습니다")
        self.assertEqual(self.requests, [left.download_url], "묶음을 한 번만 받아야 합니다")
        # 압축 밖으로 나가는 경로와 BVH가 아닌 멤버는 무시한다.
        self.assertFalse((self.directory.parent / "escape.bvh").exists())
        self.assertFalse((self.directory / "escape.bvh").exists())
        self.assertFalse((self.directory / "ACCAD/notes.txt").exists())
        manifest = library.read_manifest(self.directory)
        self.assertEqual(sorted(manifest), ["ACCAD/A_Run.bvh", "ACCAD/A_Walk.bvh"])
        self.assertEqual(manifest["ACCAD/A_Run.bvh"]["name"], "검사 달리기")
        # 이미 풀린 항목은 네트워크를 다시 쓰지 않는다.
        self.requests.clear()
        with patch.object(downloader, "entries_in_archive", lambda url: (left, right)):
            again = downloader.download_asset(right, self.directory)
        self.assertEqual(again, (self.directory / "ACCAD/A_Run.bvh").resolve())
        self.assertEqual(self.requests, [])

    def test_archive_with_wrong_checksum_installs_nothing(self):
        payload, left, right = self._archive_pair()
        broken = replace(left, archive_sha256="0" * 64)
        with patch.object(downloader, "entries_in_archive", lambda url: (broken, right)), \
             patch.object(downloader, "urlopen", lambda request, timeout=None: MemoryResponse(payload)):
            with self.assertRaises(ValueError):
                downloader.download_asset(broken, self.directory)
        self.assertFalse((self.directory / "ACCAD").exists(), "검증 실패인데 파일이 남았습니다")
        self.assertEqual(library.read_manifest(self.directory), {})

    def test_archive_member_content_mismatch_is_refused(self):
        payload, left, right = self._archive_pair()
        lying = replace(right, sha256=hashlib.sha256(b"different").hexdigest())
        with patch.object(downloader, "entries_in_archive", lambda url: (left, lying)), \
             patch.object(downloader, "urlopen", lambda request, timeout=None: MemoryResponse(payload)):
            with self.assertRaises(ValueError):
                downloader.download_asset(left, self.directory)

    def test_download_creates_verified_file_and_searchable_index(self):
        result = downloader.download_asset(self.entry, self.directory, opener=self.opener)
        self.assertEqual(Path(result).read_bytes(), BVH_BYTES)
        self.assertEqual(self.requests, [self.entry.download_url])
        assets = library.scan_library(self.directory)
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0].name, self.entry.name)
        self.assertEqual(Path(assets[0].path), Path(result).resolve())
        self.assertEqual(library.search_assets(assets, self.entry.tags[0]), assets)
        manifest = json.loads((self.directory / "motions.json").read_text(encoding="utf-8"))
        metadata = manifest["motions"][0]
        self.assertEqual(metadata["blob_sha1"], self.entry.blob_sha1)
        self.assertEqual(metadata["download_url"], self.entry.download_url)
        self.assertEqual(metadata["source_url"], self.entry.source_url)
        self.assertEqual(metadata["license_url"], self.entry.license_url)
        self.assertEqual(metadata["license_note"], self.entry.license_note)
        self.assertFalse(list(self.directory.rglob("*.part")))

    def test_existing_user_file_is_preserved(self):
        target = self.directory / self.entry.local_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"user-owned-motion")
        with self.assertRaises((ValueError, RuntimeError, OSError)):
            downloader.download_asset(self.entry, self.directory, opener=self.opener)
        self.assertEqual(target.read_bytes(), b"user-owned-motion")
        self.assertFalse(list(self.directory.rglob("*.part")))

    def test_hash_failure_does_not_publish_partial_file_or_index(self):
        for wrong in (replace(self.entry, sha256="0" * 64), replace(self.entry, blob_sha1="0" * 40)):
            with self.subTest(entry=wrong.sha256[:4] + wrong.blob_sha1[:4]):
                with self.assertRaises((ValueError, RuntimeError, OSError)):
                    downloader.download_asset(wrong, self.directory, opener=self.opener)
                self.assertFalse((self.directory / wrong.local_path).exists())
                self.assertEqual(library.scan_library(self.directory), [])
                self.assertFalse(list(self.directory.rglob("*.part")))

    def test_entry_without_checksum_is_refused(self):
        naked = replace(self.entry, sha256="", blob_sha1="")
        with self.assertRaises(ValueError):
            downloader.download_asset(naked, self.directory, opener=self.opener)
        self.assertEqual(self.requests, [])

    def test_blob_hash_matches_git_object_format(self):
        self.assertEqual(downloader.git_blob_sha1(b""), "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391")
        self.assertEqual(downloader.git_blob_sha1(b"hello\n"), "ce013625030ba8dba906f756967f9e9ca394464a")

    def test_truncated_or_non_bvh_content_is_not_registered(self):
        cases = ((BVH_BYTES, len(BVH_BYTES) + 1), (b"<html>missing</html>", len(b"<html>missing</html>")))
        for payload, size in cases:
            entry = replace(self.entry, sha256=hashlib.sha256(payload).hexdigest(),
                            blob_sha1=downloader.git_blob_sha1(payload), size_bytes=size)
            with self.subTest(payload=payload[:16]), self.assertRaises(ValueError):
                downloader.download_asset(entry, self.directory, opener=lambda *args, **kwargs: MemoryResponse(payload))
            self.assertFalse((self.directory / entry.local_path).exists())
            self.assertEqual(library.scan_library(self.directory), [])
            self.assertFalse(list(self.directory.rglob("*.part")))

    def test_pre_cancelled_download_does_not_touch_network(self):
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(downloader.DownloadCancelled):
            downloader.download_asset(self.entry, self.directory, opener=self.opener, cancel_event=cancelled)
        self.assertEqual(self.requests, [])
        self.assertFalse((self.directory / self.entry.local_path).exists())

    def test_midstream_cancel_removes_partial_file(self):
        cancelled = threading.Event()
        with self.assertRaises(downloader.DownloadCancelled):
            downloader.download_asset(self.entry, self.directory, opener=self.opener,
                                      cancel_event=cancelled, progress=lambda *_: cancelled.set())
        self.assertFalse((self.directory / self.entry.local_path).exists())
        self.assertFalse(list(self.directory.rglob("*.part")))

    def test_existing_verified_download_merges_metadata_without_network(self):
        original = {"file": "user.fbx", "name": "기존 사용자 모션", "tags": ["custom"]}
        (self.directory / "motions.json").write_text(json.dumps({"motions": [original]}), encoding="utf-8")
        result = downloader.download_asset(self.entry, self.directory, opener=self.opener)
        again = downloader.download_asset(self.entry, self.directory, opener=self.opener)
        self.assertEqual(result, again)
        self.assertEqual(len(self.requests), 1)
        motions = json.loads((self.directory / "motions.json").read_text(encoding="utf-8"))["motions"]
        self.assertEqual(len(motions), 2)
        self.assertIn(original, motions)

    def test_background_job_uses_mock_network_and_finishes(self):
        with patch.object(downloader, "urlopen", self.opener):
            job = downloader.DownloadJob(self.entry, self.directory)
            job._thread.join(timeout=5)
        self.assertTrue(job.done, "다운로드 작업이 종료되지 않았습니다")
        self.assertIsNone(job.error)
        self.assertEqual(Path(job.result).read_bytes(), BVH_BYTES)
        self.assertEqual(job.progress, 1.0)


if __name__ == "__main__":
    unittest.main()
