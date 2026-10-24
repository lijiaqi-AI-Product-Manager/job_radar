"""文档一致性自检：相对链接是否断、版本号是否一致、安装说法是否统一。

由来（2026-10-24 实测反馈）：README 徽章写 1.0.1、正文写 1.0.2、代码是 1.0.3；
README 说"尚未发布到 PyPI"，Skill 第一句却让用户 `pip install jobradar`；
内部过程文档混在 docs/ 下。这些都不该靠人肉发现。

用法：uv run python scripts/check_docs_links.py   （CI 里跑，失败即红）
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "node_modules", ".uv-cache", "t-tmp", "dist", "build"}
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
# 明确的"未来时"说明，允许出现在安装指引旁边
ALLOW_PIP_HINT = ("尚未发布", "发布后", "PYPI_ENABLED", "Trusted Publishing", "PUBLISHING")


def md_files() -> list[Path]:
    out = []
    for p in ROOT.rglob("*.md"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        out.append(p)
    return sorted(out)


def broken_links(files: list[Path]) -> list[str]:
    bad = []
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        for target in LINK.findall(text):
            t = target.strip()
            if not t or t.startswith(("http://", "https://", "mailto:", "#", "data:")):
                continue
            path = t.split("#", 1)[0].split(" ", 1)[0]
            if not path:
                continue
            if not (f.parent / path).exists() and not (ROOT / path).exists():
                bad.append(f"{f.relative_to(ROOT)} -> {t}")
    return bad


def versions() -> list[str]:
    py = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    ver = re.search(r'^version = "([^"]+)"', py, re.M).group(1)
    problems = []
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    badge = re.search(r"badge/version-([0-9.]+)-", readme)
    if badge and badge.group(1) != ver:
        problems.append(f"README 徽章 {badge.group(1)} != pyproject {ver}")
    body = re.search(r"代码 v?([0-9]+\.[0-9]+\.[0-9]+)", readme)
    if body and body.group(1) != ver:
        problems.append(f"README 正文 {body.group(1)} != pyproject {ver}")
    return problems


def install_claims() -> list[str]:
    """`pip install jobradar`（不带 git+）只能出现在明确说明"尚未发布"的上下文里。"""
    problems = []
    for f in md_files():
        text = f.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"pip install \"?jobradar", text):
            if "git+" in text[m.start():m.start() + 60]:
                continue
            window = text[max(0, m.start() - 400):m.start() + 400]
            if any(h in window for h in ALLOW_PIP_HINT):
                continue
            problems.append(f"{f.relative_to(ROOT)}: `pip install jobradar` 未说明尚未发布")
    return problems


def main() -> int:
    files = md_files()
    bad = broken_links(files)
    ver = versions()
    inst = install_claims()
    print(f"扫描 {len(files)} 个 markdown 文件")
    for title, items in (("断链", bad), ("版本不一致", ver), ("安装说法", inst)):
        if items:
            print(f"\n[{title}] {len(items)} 处")
            for it in items[:30]:
                print("  -", it)
    if bad or ver or inst:
        return 1
    print("OK：无断链，版本与安装说法一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
