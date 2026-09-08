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
ALLOWED_HOSTS = frozenset({"raw.githubusercontent.com"})
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
        download_url = _text(source, "base_url") + remote_path
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


def get_source(identifier):
    entry = _BY_ID.get(identifier)
    if entry is None:
        raise ValueError("공개 모션 카탈로그에서 항목을 찾을 수 없습니다.")
    return entry
