"""로컬 모션 샘플 라이브러리 인덱스와 가져오기 보조 함수."""

from dataclasses import dataclass
from pathlib import Path
import json
import re
import hashlib


SUPPORTED_EXTENSIONS = {".bvh", ".fbx"}
DEFAULT_MOTION_DIR = "motions"


@dataclass(frozen=True)
class MotionAsset:
    identifier: str
    name: str
    path: str
    file_type: str
    tags: tuple[str, ...]
    description: str = ""

    def to_dict(self):
        return {
            "id": self.identifier,
            "name": self.name,
            "path": self.path,
            "file_type": self.file_type,
            "tags": list(self.tags),
            "description": self.description,
        }


def addon_root():
    return Path(__file__).resolve().parents[1]


def default_library_path():
    return addon_root() / DEFAULT_MOTION_DIR


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
    data = json.loads(path.read_text(encoding="utf-8"))
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
        for field in ("name", "description"):
            if field in item and not isinstance(item[field], str):
                raise ValueError(f"motions.json의 {field}는 문자열이어야 합니다.")
        tags = item.get("tags", [])
        if not isinstance(tags, (str, list)) or isinstance(tags, list) and not all(isinstance(tag, str) for tag in tags):
            raise ValueError("motions.json의 tags는 문자열 또는 문자열 배열이어야 합니다.")
        result[file_name] = item
    return result


def make_asset(filepath, name="", tags="", description=""):
    path = Path(filepath).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"모션 파일을 찾을 수 없습니다: {path}")
    extension = path.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError("BVH 또는 FBX 모션 파일만 등록할 수 있습니다.")
    if not isinstance(name, str) or not isinstance(description, str):
        raise ValueError("모션 이름과 설명은 문자열이어야 합니다.")
    title = name.strip() or path.stem.replace("_", " ").replace("-", " ")
    identifier = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:20]
    return MotionAsset(identifier, title, str(path), extension[1:], normalize_tags(tags) or normalize_tags(title), description.strip())


def scan_library(directory):
    root = Path(directory).expanduser().resolve()
    if not root.exists():
        return []
    if not root.is_dir():
        raise ValueError(f"모션 라이브러리 경로가 폴더가 아닙니다: {root}")
    manifest = read_manifest(root)
    assets = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        relative = path.relative_to(root).as_posix()
        meta = manifest.get(relative, {})
        tags = normalize_tags(meta.get("tags", ()))
        if not tags:
            tags = normalize_tags(path.stem.replace("_", " ").replace("-", " "))
        name = str(meta.get("name") or path.stem.replace("_", " ").replace("-", " ")).strip()
        description = str(meta.get("description") or "").strip()
        assets.append(make_asset(path, name, tags, description))
    return assets


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


def assets_to_json(assets):
    return json.dumps([asset.to_dict() for asset in assets], ensure_ascii=False)


def assets_from_json(text):
    data = json.loads(text or "[]")
    result = []
    if not isinstance(data, list):
        raise ValueError("모션 인덱스가 배열이 아닙니다.")
    used_ids = set()
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("모션 인덱스 항목은 객체여야 합니다.")
        for field in ("id", "name", "path", "file_type"):
            if not isinstance(item.get(field), str) or not item[field]:
                raise ValueError(f"모션 인덱스의 {field}가 잘못되었습니다.")
        if item["file_type"] not in {"bvh", "fbx"} or Path(item["path"]).suffix.lower() != "." + item["file_type"]:
            raise ValueError("모션 인덱스 형식과 파일 확장자가 일치하지 않습니다.")
        if not isinstance(item.get("tags", []), list) or not all(isinstance(tag, str) for tag in item.get("tags", [])):
            raise ValueError("모션 태그는 문자열 배열이어야 합니다.")
        if not isinstance(item.get("description", ""), str):
            raise ValueError("모션 설명은 문자열이어야 합니다.")
        if item["id"] in used_ids:
            raise ValueError("모션 인덱스 ID가 중복되었습니다.")
        used_ids.add(item["id"])
        result.append(MotionAsset(
            identifier=str(item["id"]),
            name=str(item["name"]),
            path=str(item["path"]),
            file_type=str(item["file_type"]),
            tags=tuple(str(tag) for tag in item.get("tags", [])),
            description=str(item.get("description", "")),
        ))
    return result
