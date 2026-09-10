"""동봉한 motion_catalog.json에서 공개 모션 카탈로그를 읽는다.

카탈로그는 scripts/build_catalog.py가 공개 저장소의 고정 리비전에서 생성한다.
각 항목은 정확한 바이트 크기와 git blob SHA-1을 담고 있어, 내려받은 파일이
그 리비전의 내용과 같은지 로컬에서 검증할 수 있다.
"""

from dataclasses import dataclass, field
import json
from pathlib import Path
from urllib.parse import urlparse

CATALOG_FILE = "motion_catalog.json"
# 다운로드를 허용하는 호스트. 카탈로그가 고정 리비전과 체크섬을 함께 담는 곳만 넣는다.
ALLOWED_HOSTS = frozenset({"raw.githubusercontent.com", "accad.osu.edu"})
MAX_FILE_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class SourceEntry:
    id: str
    name: str
    tags: tuple[str, ...]
    source_name: str
    source_url: str
    license_note: str
    license_url: str
    download_url: str
    local_path: str
    size_bytes: int
    blob_sha1: str = ""
    sha256: str = ""
    description: str = ""
    category: str = ""
    frames: int = 0
    fps: float = 0.0
    rig_profile: str = ""
    commercial_use: bool = True
    # ZIP으로만 배포되는 출처. download_url이 압축 파일을 가리키고 archive_member가 그 안의 BVH다.
    archive_member: str = ""
    archive_sha256: str = ""
    archive_size_bytes: int = 0


def _text(mapping, key, default=""):
    value = mapping.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"카탈로그의 {key}는 문자열이어야 합니다.")
    return value.strip()


def load_catalog(path=None):
    """카탈로그 파일을 검증하며 SourceEntry 튜플로 읽는다."""
    location = Path(path) if path else Path(__file__).resolve().parent / CATALOG_FILE
    document = json.loads(location.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError("지원하지 않는 모션 카탈로그 형식입니다.")
    sources = document.get("sources")
    motions = document.get("motions")
    if not isinstance(sources, dict) or not isinstance(motions, list):
        raise ValueError("모션 카탈로그에 sources 또는 motions가 없습니다.")
    entries = []
    seen = set()
    for item in motions:
        if not isinstance(item, dict):
            raise ValueError("모션 카탈로그 항목은 객체여야 합니다.")
        source = sources.get(item.get("source"))
        if not isinstance(source, dict):
            raise ValueError(f"모션 {item.get('id')}의 출처 정의를 찾을 수 없습니다.")
        identifier = _text(item, "id")
        remote_path = _text(item, "remote_path")
        local_path = _text(item, "local_path")
        size = item.get("size_bytes")
        if not identifier or identifier in seen:
            raise ValueError(f"모션 카탈로그 ID가 비었거나 중복입니다: {identifier}")
        seen.add(identifier)
        if not isinstance(size, int) or not 0 < size <= MAX_FILE_BYTES:
            raise ValueError(f"모션 {identifier}의 크기가 지원 범위를 벗어났습니다.")
        relative = Path(local_path)
        if not local_path or relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".bvh":
            raise ValueError(f"모션 {identifier}의 저장 경로가 올바르지 않습니다.")
        archive = _text(item, "archive")
        archive_member = ""
        archive_digest = ""
        archive_size = 0
        if archive:
            member = Path(remote_path)
            if member.is_absolute() or ".." in member.parts or member.suffix.lower() != ".bvh":
                raise ValueError(f"모션 {identifier}의 압축 내부 경로가 올바르지 않습니다.")
            archive_member = remote_path
            archive_digest = _text(item, "archive_sha256")
            archive_size = item.get("archive_size_bytes")
            if len(archive_digest) != 64:
                raise ValueError(f"모션 {identifier}의 압축 파일 체크섬이 없습니다.")
            if not isinstance(archive_size, int) or not 0 < archive_size <= MAX_FILE_BYTES:
                raise ValueError(f"모션 {identifier}의 압축 파일 크기가 지원 범위를 벗어났습니다.")
        download_url = _text(source, "base_url") + (archive or remote_path)
        parsed = urlparse(download_url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
            raise ValueError(f"모션 {identifier}의 다운로드 주소를 신뢰할 수 없습니다.")
        blob = _text(item, "blob_sha1")
        digest = _text(item, "sha256")
        if len(blob) not in (0, 40) or len(digest) not in (0, 64) or not (blob or digest):
            raise ValueError(f"모션 {identifier}에 검증 가능한 체크섬이 없습니다.")
        tags = item.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ValueError(f"모션 {identifier}의 태그는 문자열 배열이어야 합니다.")
        entries.append(SourceEntry(
            id=identifier, name=_text(item, "name"), tags=tuple(tags),
            source_name=_text(source, "source_name"), source_url=_text(source, "source_url"),
            license_note=_text(source, "license_note"), license_url=_text(source, "license_url"),
            download_url=download_url, local_path=local_path, size_bytes=size,
            blob_sha1=blob, sha256=digest, description=_text(item, "description"),
            category=_text(item, "category"), frames=int(item.get("frames") or 0),
            fps=float(item.get("fps") or 0.0), rig_profile=_text(source, "rig_profile"),
            commercial_use=bool(source.get("commercial_use", True)),
            archive_member=archive_member, archive_sha256=archive_digest,
            archive_size_bytes=archive_size,
        ))
    if not entries:
        raise ValueError("모션 카탈로그가 비어 있습니다.")
    return tuple(entries)


def load_categories(path=None):
    location = Path(path) if path else Path(__file__).resolve().parent / CATALOG_FILE
    document = json.loads(location.read_text(encoding="utf-8"))
    categories = document.get("categories", {})
    return dict(categories) if isinstance(categories, dict) else {}


CATALOG = load_catalog()
CATEGORIES = load_categories()
_BY_ID = {entry.id: entry for entry in CATALOG}


def entries_in_archive(download_url):
    """같은 압축 파일에서 나오는 모든 항목. 한 번 받으면 전부 풀어 등록한다."""
    return tuple(entry for entry in CATALOG if entry.archive_member and entry.download_url == download_url)


def get_source(identifier):
    entry = _BY_ID.get(identifier)
    if entry is None:
        raise ValueError("공개 모션 카탈로그에서 항목을 찾을 수 없습니다.")
    return entry
