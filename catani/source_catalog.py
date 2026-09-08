"""출처와 체크섬을 확인한 공개 모션 데이터 카탈로그."""

from dataclasses import dataclass


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
    sha256: str
    size_bytes: int
    description: str = ""


CMU_URL = "https://mocap.cs.cmu.edu/"
CMU_LICENSE_NOTE = "연구·상업 제품에 사용 가능. 변환본을 포함한 모션 데이터 자체 재판매 금지. CMU 출처 고지 권장."
CMU_SOURCE_NAME = "CMU Graphics Lab · cgspeed BVH 변환 · una-dinosauria 미러"
REVISION = "09a07f54f3bbb58797325f009282d0b2048a2871"
_BASE_URL = f"https://raw.githubusercontent.com/una-dinosauria/cmu-mocap/{REVISION}/data/141"


CATALOG = tuple(
    SourceEntry(
        id=f"cmu_{clip}", name=name, tags=tags,
        source_name=CMU_SOURCE_NAME, source_url=CMU_URL,
        license_note=CMU_LICENSE_NOTE, license_url=CMU_URL,
        download_url=f"{_BASE_URL}/{clip}.bvh", local_path=f"CMU/{clip}.bvh",
        sha256=digest, size_bytes=size, description=description,
    )
    for clip, name, tags, digest, size, description in (
        ("141_16", "CMU · 손 인사", ("인사", "손", "wave", "hello", "greeting"), "d428d2c4fa8873d077537567ad32c95b9687a479a10522d314b203fddea37daf", 233582, "CMU 141_16 · Wave Hello · 300프레임 / 약 2.5초"),
        ("141_19", "CMU · 걷기", ("걷기", "이동", "walk", "walking"), "1219b0ed7ef155e4c3acbd3e18525bfb926644bc1265482873fef21705aa1808", 912115, "CMU 141_19 · Walk · 1194프레임 / 약 10초"),
        ("141_20", "CMU · 기다리기", ("대기", "기다림", "idle", "waiting"), "2389be1626ccf21e840574b43412328a5ebd9f14948167a8de97cb9f5b21b170", 584838, "CMU 141_20 · Waiting · 764프레임 / 약 6.4초"),
    )
)


def get_source(identifier):
    entry = next((entry for entry in CATALOG if entry.id == identifier), None)
    if entry is None:
        raise ValueError("공개 모션 카탈로그에서 항목을 찾을 수 없습니다.")
    return entry
