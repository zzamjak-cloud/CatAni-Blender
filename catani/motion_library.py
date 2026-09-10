"""공개 카탈로그와 로컬 파일을 한 목록으로 합치는 모션 인덱스."""

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os
import re
import tempfile

from .source_catalog import CATALOG


SUPPORTED_EXTENSIONS = {".bvh", ".fbx"}
DEFAULT_MOTION_DIR = "motions"
TEXT_FIELDS = ("name", "description", "source_name", "source_url", "license_note", "license_url", "download_url", "sha256", "blob_sha1")


@dataclass(frozen=True)
class MotionAsset:
    """목록의 한 줄. available=False면 아직 받지 않은 공개 모션이다."""

    identifier: str
    name: str
    path: str
    file_type: str
    tags: tuple[str, ...] = ()
    description: str = ""
    source_name: str = ""
    source_url: str = ""
    license_note: str = ""
    license_url: str = ""
    download_url: str = ""
    sha256: str = ""
    blob_sha1: str = ""
    source_id: str = ""
    size_bytes: int = 0
    available: bool = True
    category: str = ""


def addon_root():
    return Path(__file__).resolve().parents[1]


def bundled_library_path():
    """애드온에 동봉한 읽기 전용 예제 모션 폴더.

    설치본은 ZIP 루트의 motions/가 패키지 디렉터리 안으로 풀리고, 개발 소스는
    저장소 루트에 있다. 두 배치를 모두 찾는다.
    """
    package = Path(__file__).resolve().parent
    for candidate in (package / DEFAULT_MOTION_DIR, package.parent / DEFAULT_MOTION_DIR):
        if candidate.is_dir():
            return candidate
    return package / DEFAULT_MOTION_DIR


def default_library_path():
    return bundled_library_path()


def normalize_tags(value):
    if isinstance(value, str):
        values = re.split(r"[,\s]+", value)
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        values = ()
    result = []
    for item in values:
        text = str(item).strip().casefold()
        if text and text not in result:
            result.append(text)
    return tuple(result)


def read_manifest(directory):
    path = Path(directory) / "motions.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"motions.json 형식이 잘못되었습니다: {error}") from None
    if not isinstance(data, dict):
        raise ValueError("motions.json 최상위 값은 객체여야 합니다.")
    assets = data.get("motions", [])
    if not isinstance(assets, list):
        raise ValueError("motions.json의 motions는 배열이어야 합니다.")
    result = {}
    for item in assets:
        if not isinstance(item, dict) or "file" not in item:
            raise ValueError("motions.json 항목에는 file이 필요합니다.")
        file_name = item["file"]
        if not isinstance(file_name, str) or not file_name or Path(file_name).is_absolute() or ".." in Path(file_name).parts:
            raise ValueError("motions.json의 file은 폴더 내부 상대 경로여야 합니다.")
        if file_name in result:
            raise ValueError(f"motions.json에 파일이 중복되었습니다: {file_name}")
        for name in TEXT_FIELDS:
            if name in item and not isinstance(item[name], str):
                raise ValueError(f"motions.json의 {name}는 문자열이어야 합니다.")
        tags = item.get("tags", [])
        if not isinstance(tags, (str, list)) or isinstance(tags, list) and not all(isinstance(tag, str) for tag in tags):
            raise ValueError("motions.json의 tags는 문자열 또는 문자열 배열이어야 합니다.")
        result[file_name] = item
    return result


def catalog_entry_for(relative="", download_url=""):
    """로컬 파일이 어느 공개 카탈로그 항목인지 찾는다. 주소가 있으면 그것을 먼저 믿는다."""
    if download_url:
        matched = next((entry for entry in CATALOG if entry.download_url == download_url), None)
        if matched is not None:
            return matched
    key = str(relative).strip().replace("\\", "/")
    return next((entry for entry in CATALOG if key and entry.local_path == key), None)


def update_manifest(directory, relative, fields):
    """motions.json의 항목 하나를 갱신한다. 임시 파일에 쓰고 교체해 중간 상태를 남기지 않는다."""
    library = Path(directory).expanduser().resolve()
    if not library.is_dir():
        raise ValueError(f"모션 폴더를 찾을 수 없습니다: {library}")
    key = str(relative).replace("\\", "/")
    if not key or Path(key).is_absolute() or ".." in Path(key).parts:
        raise ValueError("모션 폴더 안의 상대 경로만 기록할 수 있습니다.")
    manifest = read_manifest(library)
    index = library / "motions.json"
    document = json.loads(index.read_text(encoding="utf-8")) if index.exists() else {"schema_version": 1}
    entry = dict(manifest.get(key, {}))
    entry.update(fields)
    entry["file"] = key
    manifest[key] = entry
    document["motions"] = list(manifest.values())
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=library, prefix=".catani-index-", suffix=".part", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(document, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, index)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return entry


def make_asset(filepath, meta=None, relative=""):
    """로컬 파일 하나를 목록 항목으로 만든다. meta는 motions.json 항목이다.

    motions.json이 없어도 폴더 안 상대 경로가 공개 카탈로그와 맞으면 그 이름과
    출처를 살린다. 예전 버전이 받아 둔 `CMU/105_59.bvh`가 목록에서 `105 59`로만
    보이던 문제를 막는다.
    """
    meta = meta or {}
    path = Path(filepath).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"모션 파일을 찾을 수 없습니다: {path}")
    extension = path.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError("BVH 또는 FBX 모션 파일만 등록할 수 있습니다.")
    text = {}
    for name in TEXT_FIELDS:
        value = meta.get(name, "")
        if not isinstance(value, str):
            raise ValueError(f"모션 {name}는 문자열이어야 합니다.")
        text[name] = value.strip()
    title = text.pop("name")
    source = catalog_entry_for(relative, text["download_url"])
    if source is not None:
        title = title or source.name
        for field, value in (("description", source.description), ("source_name", source.source_name),
                             ("source_url", source.source_url), ("license_note", source.license_note),
                             ("license_url", source.license_url), ("download_url", source.download_url),
                             ("blob_sha1", source.blob_sha1), ("sha256", source.sha256)):
            text[field] = text[field] or value
    title = title or path.stem.replace("_", " ").replace("-", " ")
    tags = normalize_tags(meta.get("tags", ()))
    if not tags and source is not None:
        tags = normalize_tags(source.tags)
    return MotionAsset(
        identifier=hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:20],
        name=title, path=str(path), file_type=extension[1:],
        tags=tags or normalize_tags(title),
        source_id=source.id if source else "", size_bytes=path.stat().st_size,
        available=True, category=source.category if source else "", **text,
    )


def read_length(path):
    """BVH의 MOTION 머리글만 읽어 (프레임 수, fps)를 돌려준다. 표본을 읽지 않으므로 값이 싸다."""
    frames, frame_time = 0, 0.0
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            lowered = line.strip().lower()
            if lowered.startswith("frames:"):
                frames = int(float(lowered.split(":", 1)[1]))
            elif lowered.startswith("frame time:"):
                frame_time = float(lowered.split(":", 1)[1])
                break
    return frames, (1.0 / frame_time if frame_time > 0 else 0.0)


def scan_library(directory):
    """폴더의 BVH/FBX를 motions.json 정보와 합쳐 정렬된 목록으로 돌려준다."""
    root = Path(directory).expanduser().resolve()
    if not root.exists():
        return []
    if not root.is_dir():
        raise ValueError(f"모션 라이브러리 경로가 폴더가 아닙니다: {root}")
    manifest = read_manifest(root)
    assets = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        relative = path.relative_to(root).as_posix()
        assets.append(make_asset(path, manifest.get(relative, {}), relative))
    return sorted(assets, key=lambda asset: asset.name)


def catalog_assets(directories=(), existing_urls=()):
    """아직 받지 않은 공개 카탈로그 항목만 목록 형태로 돌려준다."""
    roots = []
    for directory in ([directories] if isinstance(directories, (str, Path)) else directories):
        text = str(directory).strip()
        if text:
            roots.append(Path(text).expanduser().resolve())
    known = set(existing_urls)
    assets = []
    for entry in CATALOG:
        if entry.download_url in known or any((root / entry.local_path).is_file() for root in roots):
            continue
        assets.append(MotionAsset(
            identifier=f"catalog:{entry.id}", name=entry.name, path="", file_type="bvh",
            tags=normalize_tags(entry.tags), description=entry.description,
            source_name=entry.source_name, source_url=entry.source_url,
            license_note=entry.license_note, license_url=entry.license_url,
            download_url=entry.download_url, sha256=entry.sha256, blob_sha1=entry.blob_sha1,
            source_id=entry.id, size_bytes=entry.size_bytes, available=False,
            category=entry.category,
        ))
    return sorted(assets, key=lambda asset: asset.name)


def filter_assets(assets, category="", local_only=False):
    """카테고리와 '받은 모션만' 조건으로 목록을 좁힌다."""
    result = list(assets)
    if category:
        result = [asset for asset in result if asset.category == category]
    if local_only:
        result = [asset for asset in result if asset.available]
    return result


def browse(directory, query="", extra=(), category="", local_only=False):
    """받아 둔 모션을 먼저, 아직 받지 않은 공개 모션을 뒤에 놓고 검색한다.

    `extra`는 애드온에 동봉한 예제처럼 읽기 전용으로 함께 훑을 폴더다.
    """
    roots = []
    for candidate in [directory, *([extra] if isinstance(extra, (str, Path)) else extra)]:
        text = str(candidate).strip()
        if text and text not in roots:
            roots.append(text)
    local = []
    seen = set()
    for root in roots:
        for asset in scan_library(root):
            if asset.path not in seen:
                seen.add(asset.path)
                local.append(asset)
    local.sort(key=lambda asset: asset.name)
    remote = [] if local_only else catalog_assets(roots, {asset.download_url for asset in local if asset.download_url})
    return filter_assets(search_assets(local + remote, query), category, local_only)


def search_assets(assets, query):
    tokens = normalize_tags(query)
    if not tokens:
        return list(assets)
    matches = []
    for asset in assets:
        haystack = " ".join((asset.name, asset.description, " ".join(asset.tags))).casefold()
        if all(token in haystack for token in tokens):
            matches.append(asset)
    return matches
