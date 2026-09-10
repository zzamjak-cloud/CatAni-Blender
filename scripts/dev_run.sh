#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ADDON_ROOT="$PROJECT_ROOT/catani"
[[ -f "$ADDON_ROOT/blender_manifest.toml" ]] || { echo "CatAni 매니페스트를 찾을 수 없습니다." >&2; exit 1; }
ADDON_ID="$(sed -nE 's/^id[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/p' "$ADDON_ROOT/blender_manifest.toml")"
[[ "$ADDON_ID" == catani ]] || { echo "예상하지 못한 애드온 ID입니다: $ADDON_ID" >&2; exit 1; }
MINIMUM_VERSION="$(sed -nE 's/^blender_version_min[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/p' "$ADDON_ROOT/blender_manifest.toml")"
[[ -n "$MINIMUM_VERSION" ]] || { echo "매니페스트에서 blender_version_min을 읽지 못했습니다." >&2; exit 1; }

# 실행 파일에서 실제 버전을 읽는다. 폴더 이름은 실제 버전과 다를 수 있다.
read_blender_version() {
    [[ -x "$1" ]] || return 1
    "$1" --version 2>/dev/null | sed -nE '1s/^Blender ([0-9]+\.[0-9]+(\.[0-9]+)?).*/\1/p'
}

# sort -V는 플랫폼마다 동작이 달라 점으로 나눈 세 자리를 직접 비교한다.
version_at_least() {
    awk -v have="$1" -v need="$2" 'BEGIN {
        split(have, a, "."); split(need, b, ".")
        for (i = 1; i <= 3; i++) { if (a[i] + 0 > b[i] + 0) exit 0; if (a[i] + 0 < b[i] + 0) exit 1 }
        exit 0
    }'
}

# PATH와 흔한 설치 위치에서 최소 버전을 만족하는 가장 높은 버전을 고른다. 여러 버전이 함께
# 깔린 환경에서 탐색 순서로 낮은 버전이 먼저 잡히면 애드온이 로드되지 않는다.
# 서브셸에서 부르면 TOO_OLD 누적이 사라지므로 결과를 전역 변수로 돌려준다.
find_blender() {
    local -a candidates=()
    local located pattern path version best_path='' best_version=''
    located="$(command -v blender 2>/dev/null || true)"
    if [[ -n "$located" ]]; then candidates+=("$located"); fi
    for pattern in \
        /Applications/Blender.app/Contents/MacOS/Blender \
        /Applications/Blender*/Blender.app/Contents/MacOS/Blender \
        "$HOME/Applications/Blender.app/Contents/MacOS/Blender" \
        "$HOME"/Applications/Blender*/Blender.app/Contents/MacOS/Blender \
        /opt/homebrew/bin/blender \
        /usr/local/bin/blender \
        /opt/blender*/blender
    do
        # 일치하지 않은 글롭은 문자열로 남으므로 실행 가능 여부로 걸러진다.
        if [[ -x "$pattern" ]]; then candidates+=("$pattern"); fi
    done
    for path in "${candidates[@]}"; do
        version="$(read_blender_version "$path")" || continue
        [[ -n "$version" ]] || continue
        version_at_least "$version" "$MINIMUM_VERSION" || { TOO_OLD+=("$path ($version)"); continue; }
        if [[ -z "$best_version" ]] || version_at_least "$version" "$best_version"; then
            best_path="$path"
            best_version="$version"
        fi
    done
    [[ -n "$best_path" ]] || return 1
    BLENDER_EXECUTABLE="$best_path"
    BLENDER_FULL_VERSION="$best_version"
}

TOO_OLD=()
if [[ -n "${BLENDER_BINARY:-}" ]]; then
    BLENDER_EXECUTABLE="$BLENDER_BINARY"
    [[ -x "$BLENDER_EXECUTABLE" ]] || { echo "BLENDER_BINARY가 가리키는 파일을 실행할 수 없습니다: $BLENDER_EXECUTABLE" >&2; exit 1; }
    BLENDER_FULL_VERSION="$(read_blender_version "$BLENDER_EXECUTABLE")"
    [[ -n "$BLENDER_FULL_VERSION" ]] || { echo "Blender 버전을 확인하지 못했습니다." >&2; exit 1; }
    # 명시 지정은 그대로 존중하되, 애드온이 로드되지 않을 수 있음을 알린다.
    version_at_least "$BLENDER_FULL_VERSION" "$MINIMUM_VERSION" ||
        echo "경고: Blender $BLENDER_FULL_VERSION 는 매니페스트 최소 버전 $MINIMUM_VERSION 보다 낮습니다." >&2
elif find_blender; then
    echo "Blender 자동 감지: $BLENDER_EXECUTABLE ($BLENDER_FULL_VERSION)"
elif (( ${#TOO_OLD[@]} > 0 )); then
    echo "Blender $MINIMUM_VERSION 이상이 필요합니다. 찾은 설치: ${TOO_OLD[*]}. BLENDER_BINARY 환경 변수로 직접 지정하세요." >&2
    exit 1
else
    echo "Blender 실행 파일을 찾지 못했습니다. BLENDER_BINARY 환경 변수로 경로를 지정하세요." >&2
    exit 1
fi
BLENDER_VERSION="$(printf '%s' "$BLENDER_FULL_VERSION" | sed -nE 's/^([0-9]+\.[0-9]+).*/\1/p')"
[[ "$BLENDER_VERSION" =~ ^[0-9]+\.[0-9]+$ ]] || { echo "Blender 버전을 확인하지 못했습니다." >&2; exit 1; }
export BLENDER_USER_RESOURCES="$HOME/Library/Application Support/Blender/CatAniDev/$BLENDER_VERSION"
export CATANI_DEV_SOURCE="$ADDON_ROOT"
EXTENSION_ROOT="$BLENDER_USER_RESOURCES/extensions/user_default"
ADDON_LINK="$EXTENSION_ROOT/$ADDON_ID"
mkdir -p "$EXTENSION_ROOT"
if [[ -e "$ADDON_LINK" && ! -L "$ADDON_LINK" ]]; then
    echo "기존 파일 또는 폴더를 보호하기 위해 중단합니다: $ADDON_LINK" >&2
    exit 1
fi
if [[ ! -L "$ADDON_LINK" || "$(readlink "$ADDON_LINK")" != "$ADDON_ROOT" ]]; then
    TEMP_LINK="$EXTENSION_ROOT/.${ADDON_ID}.$$"
    trap 'rm -f "$TEMP_LINK"' EXIT
    ln -s "$ADDON_ROOT" "$TEMP_LINK"
    mv -fh "$TEMP_LINK" "$ADDON_LINK"
    trap - EXIT
fi
echo "CatAni 개발 프로필: $BLENDER_USER_RESOURCES"
exec "$BLENDER_EXECUTABLE" --disable-autoexec --python-exit-code 1 --python "$PROJECT_ROOT/scripts/dev_bootstrap.py" "$@"
