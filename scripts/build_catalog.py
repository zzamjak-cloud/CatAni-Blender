"""공개 모션 저장소의 고정 리비전에서 catani/motion_catalog.json을 생성한다.

CMU 설명 인덱스와 git 트리(경로·크기·blob SHA-1)를 받아 동작 분류별로 선별하고,
HTTP Range 요청으로 각 BVH 머리말의 실제 프레임 수를 읽어 기록한다.
런타임 애드온은 이 스크립트를 쓰지 않는다. 카탈로그를 갱신할 때만 실행한다.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "catani/motion_catalog.json"
CMU_REPO = "una-dinosauria/cmu-mocap"
CMU_REVISION = "09a07f54f3bbb58797325f009282d0b2048a2871"
CMU_RAW = f"https://raw.githubusercontent.com/{CMU_REPO}/{CMU_REVISION}"

CMU_SOURCE = {
    "name": "CMU Graphics Lab Motion Capture Database",
    "source_name": "CMU Graphics Lab · cgspeed BVH 변환 · una-dinosauria 미러",
    "source_url": "https://mocap.cs.cmu.edu/",
    "license_note": "연구·상업 제품에 사용 가능. 변환본을 포함한 모션 데이터 자체 재판매 금지. CMU 출처 고지 권장.",
    "license_url": "https://mocap.cs.cmu.edu/",
    "commercial_use": True,
    "revision": CMU_REVISION,
    "base_url": CMU_RAW + "/",
    "rig_profile": "cmu",
}

# 크기가 너무 작으면 쓸 만한 동작이 없고, 너무 크면 다운로드와 굽기가 무거워진다.
MIN_BYTES = 120_000
MAX_BYTES = 6_000_000
PER_CATEGORY = 14

# (분류 키, 한국어 이름, 태그, 포함 키워드, 제외 키워드)
# 설명 한 줄에 여러 동작이 섞여 있으므로 특이한 동작을 먼저 판정하고
# walk/run 같은 일반 이동을 마지막에 둔다. 그렇지 않으면 "walk, jump, turn"이
# 모두 걷기로 분류되어 점프·회전 항목이 사라진다.
CATEGORIES = (
    ("ballet", "발레", ("발레", "ballet"), (r"\bballet\b", r"\barabesque\b", r"\bpirouette\b", r"\bplie\b", r"\bpas de\b"), ()),
    ("dance", "춤", ("춤", "댄스", "dance"), (r"\bdance\b", r"\bdancing\b", r"\bsalsa\b", r"\bcha cha\b", r"\bswing dance\b", r"\bmambo\b", r"\btango\b"), ()),
    ("kick", "발차기", ("발차기", "킥", "kick"), (r"\bkick", r"\bround ?house\b"), (r"\bsoccer\b",)),
    ("punch", "펀치", ("펀치", "복싱", "punch", "boxing"), (r"\bpunch", r"\bboxing\b", r"\bmartial\b", r"\bkarate\b", r"\bfight\b"), ()),
    ("swim", "수영 동작", ("수영", "swim"), (r"\bswim", r"\bbreast stroke\b", r"\bfree style\b", r"\bback stroke\b"), ()),
    ("basketball", "농구", ("농구", "드리블", "basketball"), (r"\bbasketball\b", r"\bdribbl"), ()),
    ("sports", "구기 운동", ("운동", "스포츠", "sports"), (r"\bsoccer\b", r"\bgolf\b", r"\bbaseball\b", r"\btennis\b", r"\bbowling\b", r"\bfrisbee\b", r"\bbat\b"), ()),
    ("motorcycle", "탈것", ("탈것", "오토바이", "motorcycle", "bike"), (r"\bmotorcycle\b", r"\bbicycle\b", r"\bbike\b"), ()),
    ("fall", "넘어짐", ("넘어짐", "낙하", "fall", "stumble"), (r"\bfall\b", r"\bfalling\b", r"\bstumble", r"\bcollapse\b", r"\bflp\b", r"\bflip"), ()),
    ("balance", "균형 잡기", ("균형", "밸런스", "balance"), (r"\bbalanc", r"\bbeam\b", r"\bone foot\b", r"\btightrope\b"), ()),
    ("crawl", "기기", ("기기", "포복", "crawl"), (r"\bcrawl", r"\bcrouch", r"\bcreep", r"\bduck under\b", r"\bgo under\b", r"\ball fours\b"), ()),
    ("sneak", "살금살금", ("살금살금", "잠행", "sneak"), (r"\bsneak", r"\btip ?toe", r"\bstealth\b"), ()),
    ("climb", "오르기", ("오르기", "등반", "climb"), (r"\bclimb", r"\bladder\b", r"\bpull up\b", r"\bplayground\b"), ()),
    ("stairs", "계단", ("계단", "오르내리기", "stairs"), (r"\bstairs\b", r"\bstep up\b", r"\bstep down\b", r"\bstep ?stool\b"), ()),
    ("stretch", "스트레칭", ("스트레칭", "준비운동", "stretch"), (r"\bstretch", r"\bwarm up\b", r"\bcalisthenics\b", r"\bjumping jack", r"\brange of motion\b"), ()),
    ("throw", "던지기", ("던지기", "투척", "throw"), (r"\bthrow", r"\btoss\b", r"\bpitch\b"), ()),
    ("pick_up", "집어 들기", ("집기", "들기", "pick up"), (r"\bpick up\b", r"\bpicking up\b", r"\blift\b", r"\bputting.*down\b"), ()),
    ("carry", "운반", ("운반", "나르기", "carry"), (r"\bcarry", r"\bcarrying\b", r"\bsuitcase\b", r"\bheavy\b", r"\bbox\b"), ()),
    ("push_pull", "밀고 당기기", ("밀기", "당기기", "push", "pull"), (r"\bpush", r"\bpulls?\b", r"\bdrag\b"), (r"\bpull up\b",)),
    ("sit", "앉기", ("앉기", "착석", "sit"), (r"\bsit\b", r"\bsitting\b", r"\bstool\b", r"\bchair\b"), ()),
    ("stand_up", "일어서기", ("일어서기", "기립", "stand up"), (r"\bstand up\b", r"\bstanding up\b", r"\bget up\b", r"\brise from\b", r"\blower self\b"), ()),
    ("wave", "손 인사", ("인사", "손흔들기", "wave", "greeting"), (r"\bwave\b", r"\bwaving\b", r"\bsalute\b", r"\bgreet", r"\bhandshake\b", r"\bshake hands\b"), ()),
    ("gesture", "몸짓", ("몸짓", "제스처", "gesture", "signal"), (r"\bsignals\b", r"\bgesture", r"\bpoint\b", r"\bnod\b", r"\bshrug\b", r"\bdirecting\b"), ()),
    ("story", "생활 동작", ("생활", "일상", "story", "daily"), (r"\bwash\b", r"\bsweep\b", r"\bdrink\b", r"\beat\b", r"\bcoffee\b", r"\bteapot\b", r"\bwindow\b", r"\bstory\b", r"\bnursery rhyme\b"), ()),
    ("jump", "점프", ("점프", "뛰기", "jump"), (r"\bjump", r"\bleap\b", r"\bbroad jump\b"), (r"\bjumping jack",)),
    ("hop", "한발 뛰기", ("한발뛰기", "홉", "hop"), (r"\bhop\b", r"\bhopping\b", r"\bskip\b", r"\bskipping\b"), ()),
    ("uneven", "험한 지형", ("지형", "울퉁불퉁", "uneven", "terrain"), (r"\buneven terrain\b", r"\brough terrain\b", r"\bnavigate\b", r"\bobstacle"), ()),
    ("turn", "방향 전환", ("회전", "방향전환", "turn"), (r"\bturn around\b", r"\bveer\b", r"\bturn\b.*degree", r"\bspin\b", r"\b(90|180|270|360)\b"), ()),
    ("sidestep", "옆걸음", ("옆걸음", "사이드스텝", "sideways"), (r"\bsideways\b", r"\bsidestep\b", r"\bside step\b", r"\bshuffle\b"), ()),
    ("backward", "뒷걸음", ("뒷걸음", "후진", "backward"), (r"\bbackward", r"\bbackwards\b"), ()),
    ("walk_slow", "느린 걷기", ("느린걷기", "산책", "walk", "slow"), (r"\bslow walk\b", r"\bwalk slow", r"\bcareful walk\b", r"\bstroll\b", r"\bcareful\b"), ()),
    ("jog", "조깅", ("조깅", "가벼운달리기", "jog"), (r"\bjog\b", r"\bjogging\b"), ()),
    ("run", "달리기", ("달리기", "질주", "run", "running"), (r"\brun\b", r"\brunning\b", r"\bsprint\b"), ()),
    ("idle", "대기", ("대기", "기다림", "정지", "idle", "wait"), (r"\bwait\b", r"\bwaiting\b", r"\bidle\b", r"\brest\b", r"\bstand\b"), ()),
    ("walk", "걷기", ("걷기", "보행", "이동", "walk"), (r"\bwalk\b", r"\bwalking\b"), ()),
)

BAD_DESCRIPTION = re.compile(r"^(unknown|\d+(\.\d+)?\s*lbs?$|\d{2,3}_\d{2}\.amc$)", re.IGNORECASE)


def request_json(url):
    request = Request(url, headers={"User-Agent": "CatAni-Catalog-Builder", "Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=90) as response:
        return json.load(response)


def request_text(url):
    request = Request(url, headers={"User-Agent": "CatAni-Catalog-Builder", "Accept": "text/plain"})
    with urlopen(request, timeout=90) as response:
        return response.read().decode("utf-8", "replace")


def request_head(url, length):
    """BVH 머리말만 Range로 받아 프레임 수와 프레임 간격을 읽는다."""
    request = Request(url, headers={"User-Agent": "CatAni-Catalog-Builder", "Range": f"bytes=0-{length - 1}"})
    with urlopen(request, timeout=90) as response:
        return response.read().decode("utf-8", "replace")


def parse_descriptions(text):
    trial = re.compile(r"^(\d{2,3})_(\d{2})\s+(.*?)\s*$")
    result = {}
    for line in text.splitlines():
        match = trial.match(line.strip())
        if match:
            result[f"{int(match.group(1))}_{match.group(2)}"] = match.group(3)
    return result


def blob_sha1(payload):
    digest = hashlib.sha1()
    digest.update(f"blob {len(payload)}\0".encode("ascii"))
    digest.update(payload)
    return digest.hexdigest()


def classify(description):
    lowered = description.lower()
    for key, korean, tags, includes, excludes in CATEGORIES:
        if any(re.search(pattern, lowered) for pattern in excludes):
            continue
        if any(re.search(pattern, lowered) for pattern in includes):
            return key, korean, tags
    return None


def motion_header(url):
    """(프레임 수, FPS)를 돌려준다. 머리말을 읽지 못하면 (0, 0.0)."""
    for length in (16384, 65536, 262144):
        try:
            text = request_head(url, length)
        except Exception:
            return 0, 0.0
        frames = re.search(r"^\s*Frames:\s*(\d+)", text, re.MULTILINE)
        interval = re.search(r"^\s*Frame Time:\s*([0-9.eE+-]+)", text, re.MULTILINE)
        if frames and interval:
            step = float(interval.group(1))
            return int(frames.group(1)), (1.0 / step if step > 0 else 0.0)
    return 0, 0.0


def collect(verbose=True):
    descriptions = parse_descriptions(request_text(f"{CMU_RAW}/cmu-mocap-index-text.txt"))
    tree = request_json(f"https://api.github.com/repos/{CMU_REPO}/git/trees/{CMU_REVISION}?recursive=1")
    if tree.get("truncated"):
        raise ValueError("git 트리가 잘려 반환되었습니다. 카탈로그를 신뢰할 수 없습니다.")
    blobs = {}
    for item in tree["tree"]:
        if item["type"] != "blob" or not item["path"].endswith(".bvh"):
            continue
        subject, _, trial = Path(item["path"]).stem.partition("_")
        blobs[f"{int(subject)}_{trial}"] = item

    buckets = {key: [] for key, *_ in CATEGORIES}
    for key in sorted(descriptions, key=lambda item: (-int(item.split("_")[0]), item)):
        blob = blobs.get(key)
        description = descriptions[key].strip()
        if blob is None or not MIN_BYTES <= blob["size"] <= MAX_BYTES or BAD_DESCRIPTION.match(description):
            continue
        matched = classify(description)
        if matched is None:
            continue
        category, korean, tags = matched
        if len(buckets[category]) >= PER_CATEGORY:
            continue
        buckets[category].append((key, description, blob, korean, tags))

    motions = []
    for key, *_ in CATEGORIES:
        for trial, description, blob, korean, tags in buckets[key]:
            url = f"{CMU_RAW}/{blob['path']}"
            frames, fps = motion_header(url)
            seconds = frames / fps if frames and fps else 0.0
            short = re.sub(r"\s+", " ", description)[:40].strip(" ,-")
            detail = f"CMU {trial} · {short}"
            if seconds:
                detail += f" · {frames}프레임 / 약 {seconds:.1f}초"
            motions.append({
                "id": f"cmu_{trial}",
                "source": "cmu",
                "category": key,
                "name": f"{korean} · {short}"[:44],
                "tags": sorted({*tags, *re.split(r"[^a-z]+", description.lower())} - {""}, key=str),
                "description": detail,
                "remote_path": blob["path"],
                "local_path": f"CMU/{Path(blob['path']).name}",
                "size_bytes": blob["size"],
                "blob_sha1": blob["sha"],
                "frames": frames,
                "fps": round(fps, 4),
            })
            if verbose:
                print(f"  {motions[-1]['id']:12s} {motions[-1]['name']}", file=sys.stderr)
    return motions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(OUTPUT))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    motions = collect(verbose=not args.quiet)
    if len({item["id"] for item in motions}) != len(motions):
        raise ValueError("카탈로그 ID가 중복되었습니다.")
    document = {
        "schema_version": 1,
        "generated_by": "scripts/build_catalog.py",
        "sources": {"cmu": CMU_SOURCE},
        "categories": {key: korean for key, korean, *_ in CATEGORIES},
        "motions": motions,
    }
    path = Path(args.output)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    counts = {}
    for item in motions:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    print(json.dumps({"catalog": str(path), "motions": len(motions), "categories": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
