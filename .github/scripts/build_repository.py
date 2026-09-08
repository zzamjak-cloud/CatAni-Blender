"""공개된 CatAni 릴리스 전체에서 Blender 원격 저장소를 만든다."""

import hashlib
import html
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib
import urllib.parse
import urllib.request
import zipfile


def request_json(url):
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def published_assets(repository):
    page = 1
    while True:
        releases = request_json(f"https://api.github.com/repos/{repository}/releases?per_page=100&page={page}")
        if not releases:
            return
        for release in releases:
            if release["draft"] or release["prerelease"]:
                continue
            tag = release["tag_name"]
            if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
                continue
            name = f"catani-{tag}.zip"
            assets = {asset["name"]: asset for asset in release["assets"]}
            if name not in assets:
                continue
            if name + ".sha256" not in assets:
                raise RuntimeError(f"릴리스 체크섬 누락: {tag}")
            yield tag, assets[name], assets[name + ".sha256"]
        page += 1


def validate_archive(path, version, checksum):
    fields = checksum.strip().split()
    if len(fields) != 2 or fields[1].lstrip("*") != path.name:
        raise RuntimeError(f"체크섬 파일 이름 불일치: {path.name}")
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if fields[0] != actual:
        raise RuntimeError(f"릴리스 ZIP SHA256 불일치: {path.name}")
    with zipfile.ZipFile(path) as archive:
        manifest = tomllib.loads(archive.read("blender_manifest.toml").decode("utf-8"))
    if manifest["id"] != "catani" or manifest["version"] != version:
        raise RuntimeError(f"릴리스 매니페스트 불일치: {path.name}")
    return actual


def rewrite_index(index, assets):
    entries = index.get("data", [])
    if len(entries) != len(assets) or not entries:
        raise RuntimeError("공식 저장소 생성 결과에서 호환 릴리스가 누락되었습니다.")
    seen = set()
    for entry in entries:
        filename = Path(urllib.parse.urlparse(entry["archive_url"]).path).name
        asset = assets[filename]
        if entry["id"] != "catani" or entry["archive_hash"] != "sha256:" + asset["sha256"]:
            raise RuntimeError(f"저장소 무결성 불일치: {filename}")
        if filename in seen:
            raise RuntimeError(f"저장소 중복 항목: {filename}")
        seen.add(filename)
        entry["archive_url"] = asset["url"]
    return index


def main():
    repository = os.environ["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise RuntimeError("GitHub 저장소 식별자가 올바르지 않습니다.")
    root = Path(os.environ["RUNNER_TEMP"]) / "catani-extension-repository"
    root.mkdir(parents=True, exist_ok=False)
    archives = root / "archives"
    archives.mkdir()
    assets = {}
    prefix = f"https://github.com/{repository}/releases/download/"
    for tag, archive, checksum in published_assets(repository):
        for asset in (archive, checksum):
            if not asset["browser_download_url"].startswith(prefix):
                raise RuntimeError("저장소 외부 릴리스 자산 URL을 거부했습니다.")
        path = archives / archive["name"]
        if path.name in assets:
            raise RuntimeError(f"릴리스 자산 중복: {path.name}")
        urllib.request.urlretrieve(archive["browser_download_url"], path)
        with urllib.request.urlopen(checksum["browser_download_url"], timeout=60) as response:
            digest = validate_archive(path, tag[1:], response.read().decode("utf-8"))
        assets[path.name] = {"url": archive["browser_download_url"], "sha256": digest}
    if not assets:
        raise RuntimeError("배포된 정식 CatAni ZIP이 없어 Pages를 갱신하지 않습니다.")
    subprocess.run([
        os.environ["BLENDER_BINARY"], "--background", "--factory-startup",
        "--command", "extension", "server-generate", "--repo-dir", str(archives),
    ], check=True, env=dict(os.environ, BLENDER_USER_RESOURCES=str(root / "profile")))
    index = rewrite_index(json.loads((archives / "index.json").read_text()), assets)
    site = Path("site")
    site.mkdir(exist_ok=False)
    (site / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (site / ".nojekyll").touch()
    links = "\n".join(f'<li><a href="{html.escape(asset["url"], quote=True)}">{html.escape(name)}</a></li>' for name, asset in assets.items())
    page = f'''<!doctype html>
<html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CatAni Blender Extension</title>
<h1>CatAni Blender Extension</h1>
<p>Blender의 Get Extensions → Repositories → Add Remote Repository에 이 페이지의 <a href="index.json">index.json</a> 주소를 등록하세요.</p>
<p>Check for Updates on Startup은 새 버전 확인과 알림을 활성화합니다. 설치는 사용자 승인 후 진행됩니다.</p>
<ul>{links}</ul></html>\n'''
    (site / "index.html").write_text(page, encoding="utf-8")
    print(f"공식 Blender 저장소 생성 완료: {len(assets)}개 릴리스")


if __name__ == "__main__":
    main()
