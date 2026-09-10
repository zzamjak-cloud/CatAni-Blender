"""공개 BVH를 검증하여 내려받고 로컬 인덱스에 출처를 기록한다."""

import hashlib
import io
import os
from pathlib import Path
import tempfile
import threading
import zipfile
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .motion_library import read_manifest, update_manifest
from .source_catalog import ALLOWED_HOSTS, MAX_FILE_BYTES, entries_in_archive

# 압축 폭탄 방어. ACCAD 배포본은 풀어도 40MB를 넘지 않는다.
MAX_ARCHIVE_EXPANDED_BYTES = 256 * 1024 * 1024


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
    """이미 손으로 바꿔 둔 이름은 지우지 않고, 없을 때만 카탈로그 이름을 넣는다."""
    kept = read_manifest(root).get(entry.local_path, {})
    update_manifest(root, entry.local_path, {
        "name": kept.get("name") or entry.name, "tags": list(entry.tags),
        "description": entry.description, "source_name": entry.source_name,
        "source_url": entry.source_url, "license_note": entry.license_note,
        "license_url": entry.license_url, "download_url": entry.download_url,
        "sha256": entry.sha256, "blob_sha1": entry.blob_sha1,
    })


def _fetch(url, limit, *, progress=None, cancel_event=None, opener=None, label=""):
    """검증 전 바이트를 메모리에 모아 돌려준다. 상한을 넘으면 즉시 중단한다."""
    request = Request(url, headers={"User-Agent": "CatAni-Motion-Library", "Accept": "*/*"})
    chunks = []
    size = 0
    with (opener or urlopen)(request, timeout=20) as response:
        while True:
            _check_cancel(cancel_event)
            chunk = response.read(65536)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise ValueError("다운로드 크기가 카탈로그 정보와 다릅니다.")
            chunks.append(chunk)
            if progress:
                progress(size / limit, f"{label} · {size / 1024:.0f} / {limit / 1024:.0f} KB")
    return b"".join(chunks)


def _safe_members(archive):
    """압축 안에서 꺼내도 되는 BVH 멤버만 고른다."""
    members = []
    expanded = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = Path(info.filename)
        if name.is_absolute() or ".." in name.parts or name.suffix.lower() != ".bvh":
            continue
        expanded += info.file_size
        if expanded > MAX_ARCHIVE_EXPANDED_BYTES:
            raise ValueError("압축을 풀었을 때 크기가 지원 범위를 벗어납니다.")
        members.append(info)
    if not members:
        raise ValueError("압축 파일에 BVH가 없습니다.")
    return members


def _install_archive(entry, root, *, progress=None, cancel_event=None, opener=None):
    """압축 배포본을 한 번 받아 BVH를 모두 풀고, 요청한 항목의 경로를 돌려준다."""
    target = (root / Path(entry.local_path)).resolve()
    if not target.is_relative_to(root):
        raise ValueError("다운로드 대상은 선택한 모션 폴더 내부여야 합니다.")
    if target.is_file():
        try:
            verify_payload(entry, target.read_bytes())
        except ValueError:
            raise ValueError(f"다른 내용의 기존 파일을 보호하기 위해 중단했습니다: {target.name}") from None
        _write_metadata(entry, root)
        if progress:
            progress(1.0, "이미 받은 모션을 인덱스에 등록했습니다.")
        return target
    payload = _fetch(entry.download_url, entry.archive_size_bytes, progress=progress,
                     cancel_event=cancel_event, opener=opener, label=f"{entry.name} 묶음")
    if len(payload) != entry.archive_size_bytes:
        raise ValueError("다운로드 크기가 카탈로그 정보와 다릅니다.")
    if hashlib.sha256(payload).hexdigest() != entry.archive_sha256:
        raise ValueError("압축 파일 SHA-256 검증에 실패했습니다. 파일을 다시 받아 주세요.")
    _check_cancel(cancel_event)
    # 같은 압축에서 나오는 항목을 한 번에 등록한다. 멤버 하나마다 다시 받지 않는다.
    known = {other.archive_member: other for other in entries_in_archive(entry.download_url)}
    target.parent.mkdir(parents=True, exist_ok=True)
    installed = []
    with tempfile.TemporaryDirectory(prefix=".catani-archive-", dir=root) as staging:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for info in _safe_members(archive):
                _check_cancel(cancel_event)
                data = archive.read(info)
                other = known.get(info.filename)
                if other is not None:
                    if len(data) != other.size_bytes or (other.sha256 and hashlib.sha256(data).hexdigest() != other.sha256):
                        raise ValueError(f"압축 안의 {info.filename} 내용이 카탈로그 정보와 다릅니다.")
                    destination = root / Path(other.local_path)
                else:
                    destination = target.parent / Path(info.filename).name
                staged = Path(staging) / Path(info.filename).name
                staged.write_bytes(data)
                if not destination.exists():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(staged, destination)
                    installed.append((other, destination))
                else:
                    staged.unlink(missing_ok=True)
    for other, _destination in installed:
        if other is not None:
            _write_metadata(other, root)
    if not target.is_file():
        raise ValueError("압축 파일에서 요청한 모션을 찾지 못했습니다.")
    _write_metadata(entry, root)
    if progress:
        progress(1.0, f"{entry.name} · 묶음에서 {len(installed)}개를 풀어 등록했습니다.")
    return target


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
    if entry.archive_member:
        return _install_archive(entry, root, progress=progress, cancel_event=cancel_event, opener=opener)
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
