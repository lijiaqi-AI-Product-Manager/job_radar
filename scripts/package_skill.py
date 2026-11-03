"""导出可独立导入的求职查询技能包，不包含数据或本地配置。"""

import argparse
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skill/jobradar"


def package(destination: Path) -> None:
    files = sorted([SKILL / "SKILL.md", *(SKILL / "references").glob("*.md")])
    names = {path.relative_to(SKILL).as_posix() for path in files}
    for path in files:
        for link in re.findall(r"\[[^\]]*\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            if link.startswith(("https://", "http://", "#")):
                continue
            target = (path.parent / link.split("#", 1)[0]).resolve()
            if not target.is_relative_to(SKILL.resolve()) or target.relative_to(SKILL).as_posix() not in names:
                raise ValueError(f"技能包引用不可独立读取：{path.name} -> {link}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(SKILL).as_posix(), (2026, 11, 3, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    print(f"{destination}: {len(files)} files, {destination.stat().st_size} bytes")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    package(parser.parse_args().output)


if __name__ == "__main__":
    main()
