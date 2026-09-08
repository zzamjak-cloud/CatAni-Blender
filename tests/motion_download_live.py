"""명시적으로 허용한 경우에만 공개 카탈로그의 실제 다운로드를 확인한다."""

import argparse
import importlib
from pathlib import Path
import sys
import tempfile
import types


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-network", action="store_true", help="공개 원본 URL에 실제 접속하는 검사를 허용합니다")
    parser.add_argument("--source", help="카탈로그 ID; 생략하면 첫 항목")
    args = parser.parse_args()
    if not args.allow_network:
        parser.error("실제 다운로드 검사는 --allow-network를 명시해야 합니다.")
    root = Path(__file__).resolve().parents[1]
    package = types.ModuleType("catani")
    package.__path__ = [str(root / "catani")]
    sys.modules["catani"] = package
    catalog = importlib.import_module("catani.source_catalog")
    downloader = importlib.import_module("catani.motion_downloader")
    entry = catalog.get_source(args.source) if args.source else catalog.CATALOG[0]
    with tempfile.TemporaryDirectory(prefix="catani-live-download-") as directory:
        path = downloader.download_asset(entry, directory)
        assert Path(path).stat().st_size == entry.size_bytes
        print(f"CATANI_PASS 실제 다운로드·해시·크기: {entry.id}")


if __name__ == "__main__":
    main()
