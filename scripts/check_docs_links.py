"""文档一致性自检：相对链接是否断、版本号是否一致、安装说法是否统一。

由来（2026-10-24 实测反馈）：README 徽章写 1.0.1、正文写 1.0.2、代码是 1.0.3；
README 说"尚未发布到 PyPI"，Skill 第一句却让用户 `pip install jobradar`；
内部过程文档混在 docs/ 下。这些都不该靠人肉发现。

用法：uv run python scripts/check_docs_links.py   （CI 里跑，失败即红）
"""
import os
import re
import sys
from pathlib import Path

# Windows 的 GitHub runner 控制台是 cp1252，直接 print 中文会 UnicodeEncodeError（2026-10-24 CI 实测）
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — 被重定向的流可能不支持
        pass

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "node_modules", ".uv-cache", ".tmp", "t-tmp", "dist", "build"}
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
# 明确的"未来时"说明，允许出现在安装指引旁边
ALLOW_PIP_HINT = ("尚未发布", "发布后", "PYPI_ENABLED", "Trusted Publishing", "PUBLISHING")


def md_files() -> list[Path]:
    out = []
    for directory, dirs, files in os.walk(ROOT):
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
        out.extend(Path(directory) / name for name in files if name.endswith(".md"))
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
    # 版本唯一来源是 src/jobradar/__init__.py（pyproject 用 hatch 动态读）
    init = (ROOT / "src" / "jobradar" / "__init__.py").read_text(encoding="utf-8")
    ver = re.search(r'^__version__ = "([^"]+)"', init, re.M).group(1)
    problems = []
    if 'dynamic = ["version"]' not in py or "[tool.hatch.version]" not in py:
        problems.append("pyproject.toml 应使用 hatch 动态版本（唯一来源 src/jobradar/__init__.py）")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    badge = re.search(r"badge/version-([0-9.]+)-", readme)
    if badge and badge.group(1) != ver:
        problems.append(f"README 徽章 {badge.group(1)} != jobradar.__version__ {ver}")
    body = re.search(r"代码 v?([0-9]+\.[0-9]+\.[0-9]+)", readme)
    if body and body.group(1) != ver:
        problems.append(f"README 正文 {body.group(1)} != pyproject {ver}")
    # 发布名必须和 README 里的安装命令一致（2026-10-24 踩过：PyPI 建的是 jobsearchradar，文档写的是 jobradar）
    dist = re.search(r'^name = "([^"]+)"', py, re.M).group(1)
    for f in sorted(ROOT.glob("README*.md")):
        text = f.read_text(encoding="utf-8")
        m = re.search(r'pip install "([a-z0-9_.-]+)\[mcp\]"', text)
        if m and m.group(1).lower().replace("_", "-") != dist.lower().replace("_", "-"):
            problems.append(f"{f.name}: 安装名 {m.group(1)} != pyproject name {dist}")
    return problems


def install_claims() -> list[str]:
    """PyPI 已发布（1.1.1 起）：面向用户的文档里不该再有"尚未发布到 PyPI"。

    跳过 CHANGELOG 与 docs/internal/：那是历史记录，写的是当时的状态。
    """
    problems = []
    for f in md_files():
        rel = f.relative_to(ROOT).as_posix()
        if rel == "CHANGELOG.md" or rel.startswith("docs/internal/"):
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if not line.lstrip().startswith(("#", ">", "-", "|")):
                continue
            if "PyPI" in line and ("尚未发布" in line or "Not on PyPI" in line or "not yet on PyPI" in line):
                problems.append(f"{rel}:{i}: 仍写着「尚未发布到 PyPI」")
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
