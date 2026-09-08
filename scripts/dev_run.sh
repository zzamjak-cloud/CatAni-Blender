#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ADDON_ROOT="$PROJECT_ROOT/catani"
BLENDER_EXECUTABLE="${BLENDER_BINARY:-/Applications/Blender.app/Contents/MacOS/Blender}"
[[ -x "$BLENDER_EXECUTABLE" ]] || { echo "Blender 실행 파일을 찾을 수 없습니다: $BLENDER_EXECUTABLE" >&2; exit 1; }
[[ -f "$ADDON_ROOT/blender_manifest.toml" ]] || { echo "CatAni 매니페스트를 찾을 수 없습니다." >&2; exit 1; }
ADDON_ID="$(sed -nE 's/^id[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/p' "$ADDON_ROOT/blender_manifest.toml")"
[[ "$ADDON_ID" == catani ]] || { echo "예상하지 못한 애드온 ID입니다: $ADDON_ID" >&2; exit 1; }
BLENDER_VERSION="$("$BLENDER_EXECUTABLE" --version | sed -nE '1s/^Blender ([0-9]+\.[0-9]+).*/\1/p')"
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
