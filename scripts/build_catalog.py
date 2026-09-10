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
from concurrent.futures import ThreadPoolExecutor
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

BANDAI_REPO = "BandaiNamcoResearchInc/Bandai-Namco-Research-Motiondataset"
BANDAI_REVISION = "74ead3ba1ae4696404e6086233779f60de8bf9ef"
BANDAI_RAW = f"https://raw.githubusercontent.com/{BANDAI_REPO}/{BANDAI_REVISION}"

BANDAI_SOURCE = {
    "name": "Bandai Namco Research Motion Dataset",
    "source_name": "Bandai Namco Research Inc. · Motion Style Transfer 데이터셋",
    "source_url": f"https://github.com/{BANDAI_REPO}",
    "license_note": "CC BY-NC 4.0 · 비상업 용도만 허용합니다. 상업 제품에는 쓸 수 없고 출처 표기가 필요합니다.",
    "license_url": "https://creativecommons.org/licenses/by-nc/4.0/",
    "commercial_use": False,
    "revision": BANDAI_REVISION,
    "base_url": BANDAI_RAW + "/",
    "rig_profile": "generic",
}

# 파일명이 `dataset-N_{동작}_{스타일}_{번호}`라 별도 인덱스 없이 이름과 분류를 얻는다.
# (한국어 이름, 분류 키)
BANDAI_CONTENT = {
    "walk": ("걷기", "walk"),
    "walk-turn-left": ("걷다가 좌회전", "turn"),
    "walk-turn-right": ("걷다가 우회전", "turn"),
    "walk-back": ("뒤로 걷기", "backward"),
    "walk-left": ("왼쪽으로 걷기", "sidestep"),
    "walk-right": ("오른쪽으로 걷기", "sidestep"),
    "run": ("달리기", "run"),
    "dash": ("전력 질주", "run"),
    "raise-up-left-hand": ("왼손 들기", "gesture"),
    "raise-up-right-hand": ("오른손 들기", "gesture"),
    "raise-up-both-hands": ("두 손 들기", "gesture"),
    "wave-left-hand": ("왼손 흔들기", "wave"),
    "wave-right-hand": ("오른손 흔들기", "wave"),
    "wave-both-hands": ("두 손 흔들기", "wave"),
    "bow": ("절", "bow"),
    "bye": ("작별 인사", "wave"),
    "byebye": ("손 흔들어 작별", "wave"),
    "guide": ("길 안내", "gesture"),
    "call": ("부르기", "gesture"),
    "respond": ("응답", "gesture"),
    "punch": ("펀치", "punch"),
    "kick": ("발차기", "kick"),
    "slash": ("베기", "sword"),
    "dance-long": ("춤 (긴 것)", "dance"),
    "dance-short": ("춤 (짧은 것)", "dance"),
}

BANDAI_STYLE = {
    "normal": "보통", "active": "활발", "exhausted": "지친", "elderly": "노년",
    "feminine": "여성적", "masculine": "남성적", "masculinity": "남성적", "youthful": "젊은",
    "angry": "화난", "childish": "아이 같은", "chimpira": "불량한", "giant": "거대한",
    "happy": "행복한", "musical": "뮤지컬", "not-confident": "자신 없는", "old": "늙은",
    "proud": "당당한", "sad": "슬픈", "tired": "피곤한",
}

# 큐레이션된 단일 동작이라 CMU보다 짧다. 하한을 따로 둔다.
BANDAI_MIN_BYTES = 20_000

# 크기가 너무 작으면 쓸 만한 동작이 없고, 너무 크면 다운로드와 굽기가 무거워진다.
# 상한은 source_catalog.MAX_FILE_BYTES(32MB) 안에 둔다.
MIN_BYTES = 60_000
MAX_BYTES = 12_000_000
PER_CATEGORY = 600

# (분류 키, 한국어 이름, 태그, 포함 키워드, 제외 키워드)
# 설명 한 줄에 여러 동작이 섞여 있으므로 특이한 동작을 먼저 판정하고
# walk/run 같은 일반 이동을 마지막에 둔다. 그렇지 않으면 "walk, jump, turn"이
# 모두 걷기로 분류되어 점프·회전 항목이 사라진다.
CATEGORIES = (
    ("ballet", "발레", ("발레", "ballet"), (r"\bballet\b", r"\barabesque\b", r"\bpirouette\b", r"\bplie\b", r"\bpas de\b"), ()),
    ("dance", "춤", ("춤", "댄스", "dance"), (r"\bdance\b", r"\bdancing\b", r"\bsalsa\b", r"\bcha cha\b", r"\bswing dance\b", r"\bmambo\b", r"\btango\b", r"\bcharleston\b", r"\bmacarena\b"), ()),
    ("kick", "발차기", ("발차기", "킥", "kick"), (r"\bkick", r"\bround ?house\b"), (r"\bsoccer\b",)),
    ("punch", "펀치", ("펀치", "복싱", "punch", "boxing"), (r"\bpunch", r"\bboxing\b", r"\bmartial\b", r"\bkarate\b", r"\bfight\b"), ()),
    ("sword", "검술", ("검술", "무기", "sword", "fencing"), (r"\bsword", r"\bfenc(e|ing)\b", r"\bsabre\b", r"\bspear\b"), ()),
    ("swim", "수영 동작", ("수영", "swim"), (r"\bswim", r"\bbreast stroke\b", r"\bfree style\b", r"\bback stroke\b"), ()),
    ("basketball", "농구", ("농구", "드리블", "basketball"), (r"\bbasketball\b", r"\bdribbl"), ()),
    ("sports", "구기 운동", ("운동", "스포츠", "sports"), (r"\bsoccer\b", r"\bgolf\b", r"\bbaseball\b", r"\btennis\b", r"\bbowling\b", r"\bfrisbee\b", r"\bbat\b", r"\bputt\b", r"\btee\b", r"\bfootball\b", r"\boffensive move\b", r"\bdefensive move\b"), ()),
    ("motorcycle", "탈것", ("탈것", "오토바이", "motorcycle", "bike"), (r"\bmotorcycle\b", r"\bbicycle\b", r"\bbike\b"), ()),
    # 사람이 동물을 흉내 내는 묶음. CMU 인덱스는 `(human subject)` 꼬리표로 표시한다.
    ("animal", "동물 흉내", ("동물", "흉내", "animal", "mimic"), (r"\bhuman subject\b", r"\bprairie dog\b", r"\bwhale\b", r"\bbear\b", r"\bpenguin\b", r"\bsnake\b", r"\bchicken\b", r"\bmonkey\b", r"\bgorilla\b", r"\bmouse\b", r"\bcat\b", r"\belephant\b", r"\bdinosaur\b", r"\bdog\b"), ()),
    ("yoga", "요가·체조", ("요가", "체조", "yoga", "gymnastics"), (r"\byoga\b", r"\bcartwheel", r"\bhandstand\b", r"\bsquats?\b", r"\bsomersault\b", r"\bsalto\b", r"\bgymnast", r"\bbackflip"), ()),
    ("fall", "넘어짐", ("넘어짐", "낙하", "fall", "stumble"), (r"\bfall\b", r"\bfalling\b", r"\bstumble", r"\bcollapse\b", r"\bflp\b", r"\bflip"), ()),
    ("balance", "균형 잡기", ("균형", "밸런스", "balance"), (r"\bbalanc", r"\bbeam\b", r"\bone foot\b", r"\btightrope\b"), ()),
    ("crawl", "기기", ("기기", "포복", "crawl"), (r"\bcrawl", r"\bcrouch", r"\bcreep", r"\bduck under\b", r"\bgo under\b", r"\ball fours\b"), ()),
    ("sneak", "살금살금", ("살금살금", "잠행", "sneak"), (r"\bsneak", r"\btip ?toe", r"\bstealth\b"), ()),
    ("climb", "오르기", ("오르기", "등반", "climb"), (r"\bclimb", r"\bladder\b", r"\bpull up\b", r"\bplayground\b"), ()),
    ("stairs", "계단", ("계단", "오르내리기", "stairs"), (r"\bstairs\b", r"\bstep up\b", r"\bstep down\b", r"\bstep ?stool\b"), ()),
    ("march", "행진", ("행진", "마치", "march", "parade"), (r"\bmarch", r"\bparade\b", r"\bgoose step\b"), ()),
    ("stretch", "스트레칭", ("스트레칭", "준비운동", "stretch"), (r"\bstretch", r"\bwarm up\b", r"\bcalisthenics\b", r"\bjumping jack", r"\brange of motion\b"), ()),
    ("throw", "던지기", ("던지기", "투척", "throw"), (r"\bthrow", r"\btoss\b", r"\bpitch\b"), ()),
    ("pick_up", "집어 들기", ("집기", "들기", "pick up"), (r"\bpick up\b", r"\bpicking up\b", r"\blift\b", r"\bputting.*down\b"), ()),
    ("carry", "운반", ("운반", "나르기", "carry"), (r"\bcarry", r"\bcarrying\b", r"\bsuitcase\b", r"\bheavy\b", r"\bbox\b"), ()),
    ("push_pull", "밀고 당기기", ("밀기", "당기기", "push", "pull"), (r"\bpush", r"\bpulls?\b", r"\bdrag\b"), (r"\bpull up\b",)),
    ("sit", "앉기", ("앉기", "착석", "sit"), (r"\bsit\b", r"\bsitting\b", r"\bsits\b", r"\bstool\b", r"\bchair\b"), ()),
    ("stand_up", "일어서기", ("일어서기", "기립", "stand up"), (r"\bstand up\b", r"\bstanding up\b", r"\bget up\b", r"\brise from\b", r"\blower self\b"), ()),
    ("wave", "손 인사", ("인사", "손흔들기", "wave", "greeting"), (r"\bwave\b", r"\bwaving\b", r"\bsalute\b", r"\bgreet", r"\bhandshake\b", r"\bshake hands\b"), ()),
    ("gesture", "몸짓", ("몸짓", "제스처", "gesture", "signal"), (r"\bsignals\b", r"\bgesture", r"\bpoint\b", r"\bnod\b", r"\bshrug\b", r"\bdirecting\b"), ()),
    ("emotion", "감정 표현", ("감정", "표현", "emotion", "laugh"), (r"\blaugh", r"\bcry\b", r"\bcrying\b", r"\bangry\b", r"\bquarrel\b", r"\bcomforts?\b", r"\bshelters\b", r"\byawn\b"), ()),
    ("tool", "공구 작업", ("공구", "작업", "tool"), (r"\bwrench\b", r"\bbolt\b", r"\bscrew", r"\bunscrew", r"\bhammer", r"\bnail\b", r"\bsaw(ing)?\b", r"\bumbrella\b", r"\brope\b", r"\bdrill\b"), ()),
    ("swing", "그네·흔들기", ("그네", "흔들기", "swing"), (r"\bswing\b", r"\bswinging\b", r"\bsee ?saw\b"), ()),
    ("housework", "집안일", ("집안일", "청소", "housework"), (r"\bmop\b", r"\bvacuum", r"\bsweep", r"\bironing\b", r"\bcleaning\b", r"\bwipe\b", r"\bwash\b", r"\bdust\b"), ()),
    ("story", "생활 동작", ("생활", "일상", "story", "daily"), (r"\bdrink\b", r"\beat\b", r"\beating\b", r"\bcoffee\b", r"\bteapot\b", r"\bwindow\b", r"\bstory\b", r"\bnursery rhyme\b", r"\bconversation\b"), ()),
    ("limp", "절뚝거림", ("절뚝", "부상", "limp", "hurt"), (r"\blimp", r"\bhurt\b", r"\binjur", r"\bwounded\b"), ()),
    ("jump", "점프", ("점프", "뛰기", "jump"), (r"\bjump", r"\bleap\b", r"\bbroad jump\b"), (r"\bjumping jack",)),
    ("hop", "한발 뛰기", ("한발뛰기", "홉", "hop"), (r"\bhop\b", r"\bhopping\b", r"\bskip\b", r"\bskipping\b"), ()),
    ("uneven", "험한 지형", ("지형", "울퉁불퉁", "uneven", "terrain"), (r"\buneven terrain\b", r"\brough terrain\b", r"\bnavigate\b", r"\bobstacle", r"\bslope\b"), ()),
    ("turn", "방향 전환", ("회전", "방향전환", "turn"), (r"\bturn around\b", r"\bveer\b", r"\bturn\b.*degree", r"\bspin\b", r"\b(90|180|270|360)\b", r"\bturn\b"), ()),
    ("sidestep", "옆걸음", ("옆걸음", "사이드스텝", "sideways"), (r"\bsideways\b", r"\bsidestep\b", r"\bside step\b", r"\bside to side\b", r"\bshuffle\b"), ()),
    ("backward", "뒷걸음", ("뒷걸음", "후진", "backward"), (r"\bbackward", r"\bbackwards\b"), ()),
    ("walk_slow", "느린 걷기", ("느린걷기", "산책", "walk", "slow"), (r"\bslow ?walk\b", r"\bwalk slow", r"\bcareful walk\b", r"\bstroll\b", r"\bcareful\b"), ()),
    ("jog", "조깅", ("조깅", "가벼운달리기", "jog"), (r"\bjog\b", r"\bjogging\b"), ()),
    ("run", "달리기", ("달리기", "질주", "run", "running"), (r"\brun\b", r"\brunning\b", r"\bsprint\b"), ()),
    ("idle", "대기", ("대기", "기다림", "정지", "idle", "wait"), (r"\bwait\b", r"\bwaiting\b", r"\bidle\b", r"\brest\b", r"\bstand\b"), ()),
    ("walk", "걷기", ("걷기", "보행", "이동", "walk"), (r"\bwalk\b", r"\bwalking\b"), ()),
    ("reach", "손 뻗기·놓기", ("손뻗기", "놓기", "reach", "place"), (r"\breach", r"\bplacing\b", r"\bplace\b", r"\bputting\b", r"\bputs\b", r"\blean forward\b", r"\bgrab\b"), ()),
    ("scene", "장면 연기", ("장면", "연기", "scene", "acting"), (r"\bvacation\b", r"\bpantomime\b", r"\bacting\b", r"\bvignettes?\b", r"\bsequence\b", r"\bblind man\b", r"\bsuperhero\b", r"\bdevil\b", r"\bzombie\b", r"\bmichael jackson\b"), ()),
    ("interact", "2인 상호작용", ("2인", "상호작용", "interaction", "two subjects"), (r"\b2 subjects\b", r"\bsubjects - subject\b", r"\barm wrestle\b", r"\bshoulder rub\b", r"\bfriends meet\b", r"\bhang out\b"), ()),
    # 설명이 있는 동작을 버리지 않기 위한 마지막 묶음. 위에서 하나도 안 걸리면 여기로 온다.
    ("misc", "기타", ("기타", "misc"), (r"\S",), ()),
)

# 설명이 아예 없거나 `Unknown`·`clean`뿐인 항목이 들어가는 자리. 이름을 만들 수
# 없으므로 애드온에서 직접 이름과 분류를 지정해 쓴다.
UNKNOWN = ("unknown", "미분류", ("미분류", "unknown"))


# 의미 없는 인덱스 항목. `clean`은 정리 여부 표시일 뿐 동작 설명이 아니다.
BAD_DESCRIPTION = re.compile(r"^(unknown|clean$|\d+(\.\d+)?\s*lbs?$|\d{2,3}_\d{2}\.amc$)", re.IGNORECASE)

CLEANED_SUFFIX = re.compile(r"\s*cleaned\s*grs\s*$", re.IGNORECASE)
CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def normalize_description(text):
    """설명 한 줄을 읽을 수 있는 형태로 다듬는다.

    CMU 인덱스에는 `RunningWideLeft   CleanedGRS`처럼 도구가 붙인 꼬리표와
    붙여 쓴 이름이 섞여 있다. 꼬리표를 떼고 낱말을 띄우면 분류와 표시가 모두
    정확해진다. 띄어쓰기가 이미 있는 보통 문장은 건드리지 않는다.
    """
    cleaned = CLEANED_SUFFIX.sub("", text).strip()
    if cleaned and " " not in cleaned:
        cleaned = CAMEL_BOUNDARY.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


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
            result[f"{int(match.group(1))}_{match.group(2)}"] = normalize_description(match.group(3))
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
            # 병렬 조회 중 한 번 실패한 것일 수 있으므로 포기하지 않고 다시 시도한다.
            continue
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

    buckets = {key: [] for key, *_ in (*CATEGORIES, UNKNOWN)}
    for key in sorted(blobs, key=lambda item: (-int(item.split("_")[0]), item)):
        blob = blobs[key]
        description = descriptions.get(key, "").strip()
        if not MIN_BYTES <= blob["size"] <= MAX_BYTES:
            continue
        matched = None if not description or BAD_DESCRIPTION.match(description) else classify(description)
        if matched is None:
            # 이름을 지을 근거가 없으므로 설명을 비우고 미분류로 넘긴다.
            category, korean, tags = UNKNOWN
            description = ""
        else:
            category, korean, tags = matched
        if len(buckets[category]) >= PER_CATEGORY:
            continue
        buckets[category].append((key, description, blob, korean, tags))

    selected = [(key, *entry) for key, *_ in (*CATEGORIES, UNKNOWN) for entry in buckets[key]]
    # 항목마다 Range 요청 한 번이 필요하다. 순차 조회는 2,000건에서 20분을 넘기므로 함께 던진다.
    with ThreadPoolExecutor(max_workers=8) as pool:
        headers = list(pool.map(lambda entry: motion_header(f"{CMU_RAW}/{entry[3]['path']}"), selected))

    motions = []
    for (key, trial, description, blob, korean, tags), (frames, fps) in zip(selected, headers):
        seconds = frames / fps if frames and fps else 0.0
        short = re.sub(r"\s+", " ", description)[:40].strip(" ,-") or f"CMU {trial}"
        detail = f"CMU {trial} · {short}" if description else f"CMU {trial} · 설명 없음 · 이름과 분류를 직접 지정하세요"
        if seconds:
            detail += f" · {frames}프레임 / 약 {seconds:.1f}초"
        motions.append({
            "id": f"cmu_{trial}",
            "source": "cmu",
            "category": key,
            "name": f"{korean} · {short}"[:44],
            "tags": sorted({*tags, trial, *re.split(r"[^a-z]+", description.lower())} - {""}, key=str),
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


def collect_bandai(verbose=True):
    """Bandai Namco Research 데이터셋을 파일명에서 읽어 카탈로그 항목으로 만든다."""
    tree = request_json(f"https://api.github.com/repos/{BANDAI_REPO}/git/trees/{BANDAI_REVISION}?recursive=1")
    if tree.get("truncated"):
        raise ValueError("Bandai Namco git 트리가 잘려 반환되었습니다.")
    picked = []
    skipped = {}
    for item in tree["tree"]:
        if item["type"] != "blob" or not item["path"].endswith(".bvh"):
            continue
        stem = Path(item["path"]).stem
        parts = stem.split("_")
        if len(parts) != 4:
            skipped["이름 형식"] = skipped.get("이름 형식", 0) + 1
            continue
        _dataset, content, style, number = parts
        if content not in BANDAI_CONTENT or style not in BANDAI_STYLE:
            skipped[f"미등록 {content}/{style}"] = skipped.get(f"미등록 {content}/{style}", 0) + 1
            continue
        if not BANDAI_MIN_BYTES <= item["size"] <= MAX_BYTES:
            skipped["크기밖"] = skipped.get("크기밖", 0) + 1
            continue
        picked.append((stem, content, style, number, item))
    picked.sort(key=lambda entry: entry[0])

    with ThreadPoolExecutor(max_workers=8) as pool:
        headers = list(pool.map(lambda entry: motion_header(f"{BANDAI_RAW}/{entry[4]['path']}"), picked))

    motions = []
    for (stem, content, style, number, blob), (frames, fps) in zip(picked, headers):
        korean, category = BANDAI_CONTENT[content]
        mood = BANDAI_STYLE[style]
        seconds = frames / fps if frames and fps else 0.0
        detail = f"Bandai Namco Research · {content} · {style} · CC BY-NC 4.0(비상업)"
        if seconds:
            detail += f" · {frames}프레임 / 약 {seconds:.1f}초"
        motions.append({
            "id": f"bandai_{stem}",
            "source": "bandai",
            "category": category,
            "name": f"{korean} · {mood} {number}"[:44],
            "tags": sorted({korean, mood, "비상업", "noncommercial", "bandai",
                            *re.split(r"[^a-z]+", f"{content} {style}")} - {""}, key=str),
            "description": detail,
            "remote_path": blob["path"],
            "local_path": f"BandaiNamco/{Path(blob['path']).name}",
            "size_bytes": blob["size"],
            "blob_sha1": blob["sha"],
            "frames": frames,
            "fps": round(fps, 4),
        })
        if verbose:
            print(f"  {motions[-1]['id']:46s} {motions[-1]['name']}", file=sys.stderr)
    if skipped:
        print(json.dumps({"bandai_skipped": skipped}, ensure_ascii=False), file=sys.stderr)
    return motions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(OUTPUT))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    motions = collect(verbose=not args.quiet) + collect_bandai(verbose=not args.quiet)
    if len({item["id"] for item in motions}) != len(motions):
        raise ValueError("카탈로그 ID가 중복되었습니다.")
    document = {
        "schema_version": 1,
        "generated_by": "scripts/build_catalog.py",
        "sources": {"cmu": CMU_SOURCE, "bandai": BANDAI_SOURCE},
        # `bow`는 Bandai Namco 쪽에만 있는 분류라 CMU 분류표 뒤에 붙인다.
        "categories": {**{key: korean for key, korean, *_ in (*CATEGORIES, UNKNOWN)}, "bow": "절·인사"},
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
