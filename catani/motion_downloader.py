"""공개 BVH를 검증하여 내려받고 로컬 인덱스에 출처를 기록한다."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .motion_library import read_manifest
from .source_catalog import ALLOWED_HOSTS, MAX_FILE_BYTES


class DownloadCancelled(Exception):
    """사용자가 다운로드를 취소했다."""


def git_blob_sha1(payload):
    """git이 파일 내용에 부여하는 blob 해시. 카탈로그의 고정 리비전 값과 비교한다."""
    digest = hashlib.sha1()
    digest.update(f"blob {len(payload)}\0".encode("ascii"))
    digest.update(payload)
    return digest.hexdigest()


def verify_payload(entry, payload):
    """크기·체크섬·BVH 머리말을 모두 확인한다. 어긋나면 ValueError."""
    if len(payload) != entry.size_bytes:
        raise ValueError("다운로드 크기가 카탈로그 정보와 다릅니다.")
    if entry.blob_sha1 and git_blob_sha1(payload) != entry.blob_sha1:
        raise ValueError("다운로드 blob 체크섬 검증에 실패했습니다. 파일을 다시 받아 주세요.")
    if entry.sha256 and hashlib.sha256(payload).hexdigest() != entry.sha256:
        raise ValueError("다운로드 SHA-256 검증에 실패했습니다. 파일을 다시 받아 주세요.")
    header = payload[:16384]
    if not header.lstrip().startswith(b"HIERARCHY") or b"MOTION" not in header:
        raise ValueError("다운로드한 파일이 예상한 BVH 형식이 아닙니다.")


def _check_cancel(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise DownloadCancelled("다운로드를 취소했습니다.")


def _write_metadata(entry, root):
    manifest = read_manifest(root)
    document = json.loads((root / "motions.json").read_text(encoding="utf-8")) if (root / "motions.json").exists() else {"schema_version": 1}
    manifest[entry.local_path] = {
        "file": entry.local_path, "name": entry.name, "tags": list(entry.tags),
        "description": entry.description, "source_name": entry.source_name,
        "source_url": entry.source_url, "license_note": entry.license_note,
        "license_url": entry.license_url, "download_url": entry.download_url,
        "sha256": entry.sha256, "blob_sha1": entry.blob_sha1,
    }
    temporary = None
    document["motions"] = list(manifest.values())
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=root, prefix=".catani-index-", suffix=".part", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(document, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, root / "motions.json")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def download_asset(entry, library_dir, *, progress=None, cancel_event=None, opener=None):
    """완료된 BVH 경로를 반환한다. 기존 다른 파일은 덮어쓰지 않는다."""
    root = Path(library_dir).expanduser().resolve()
    relative = Path(entry.local_path)
    if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".bvh":
        raise ValueError("다운로드 저장 경로가 올바르지 않습니다.")
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ValueError("다운로드 대상은 선택한 모션 폴더 내부여야 합니다.")
    url = urlparse(entry.download_url)
    if url.scheme != "https" or url.hostname not in ALLOWED_HOSTS:
        raise ValueError("확인된 HTTPS 공개 데이터 주소만 다운로드할 수 있습니다.")
    if entry.size_bytes <= 0 or entry.size_bytes > MAX_FILE_BYTES:
        raise ValueError("카탈로그 파일 크기가 지원 범위를 벗어났습니다.")
    if not entry.blob_sha1 and not entry.sha256:
        raise ValueError("체크섬이 없는 항목은 내려받지 않습니다.")
    _check_cancel(cancel_event)
    root.mkdir(parents=True, exist_ok=True)
    read_manifest(root)
    if target.exists():
        if not target.is_file():
            raise ValueError(f"다른 내용의 기존 파일을 보호하기 위해 중단했습니다: {target.name}")
        try:
            verify_payload(entry, target.read_bytes())
        except ValueError:
            raise ValueError(f"다른 내용의 기존 파일을 보호하기 위해 중단했습니다: {target.name}") from None
        _write_metadata(entry, root)
        if progress:
            progress(1.0, "이미 받은 모션을 인덱스에 등록했습니다.")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    installed = False
    try:
        request = Request(entry.download_url, headers={"User-Agent": "CatAni-Motion-Library", "Accept": "text/plain"})
        with (opener or urlopen)(request, timeout=20) as response, tempfile.NamedTemporaryFile(dir=target.parent, prefix=".catani-download-", suffix=".part", delete=False) as stream:
            temporary = Path(stream.name)
            chunks = []
            size = 0
            while True:
                _check_cancel(cancel_event)
                chunk = response.read(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > entry.size_bytes:
                    raise ValueError("다운로드 크기가 카탈로그 정보와 다릅니다.")
                chunks.append(chunk)
                stream.write(chunk)
                if progress:
                    progress(size / entry.size_bytes, f"{entry.name} · {size / 1024:.0f} / {entry.size_bytes / 1024:.0f} KB")
        _check_cancel(cancel_event)
        # blob 해시는 전체 내용이 필요하다. 카탈로그가 32MB 상한을 강제하므로 메모리에 담아도 안전하다.
        verify_payload(entry, b"".join(chunks))
        # hard link 생성은 기존 파일이 있으면 실패하므로 경쟁 상황에서도 덮어쓰지 않는다.
        os.link(temporary, target)
        installed = True
        _write_metadata(entry, root)
        if progress:
            progress(1.0, f"{entry.name} 다운로드와 인덱싱을 완료했습니다.")
        return target
    except Exception:
        if installed:
            target.unlink(missing_ok=True)
        raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class DownloadJob:
    """Blender UI를 멈추지 않는 다운로드 작업. 작업 스레드는 bpy에 접근하지 않는다."""

    def __init__(self, entry, library_dir):
        self.done = False
        self.progress = 0.0
        self.status = "공개 모션 다운로드 준비 중"
        self.error = None
        self.result = None
        self._cancel = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(entry, library_dir), daemon=True)
        self._thread.start()

    def _update(self, progress, status):
        self.progress = progress
        self.status = status

    def _run(self, entry, library_dir):
        try:
            self.result = download_asset(entry, library_dir, progress=self._update, cancel_event=self._cancel)
        except Exception as error:
            self.error = str(error)
            self.status = self.error
        finally:
            self.done = True

    def cancel(self):
        self._cancel.set()
