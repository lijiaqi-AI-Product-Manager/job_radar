"""版本号与打包名的一致性：source of truth 是 src/jobradar/__init__.py。

2026-10-24 踩过两次：
1. PyPI 发布名改成 jobsearchradar 后，CLI 还按旧 distribution 名查元数据 → --version 退回 0.1.0；
2. 站点包里有旧的 jobradar-1.0.3.dist-info，导致 --version 显示 1.0.3。
所以版本号只认 __init__，并用测试钉住 pyproject / CLI / MCP 三处一致。
"""
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _init_version() -> str:
    text = (ROOT / "src" / "jobradar" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'^__version__ = "([^"]+)"', text, re.M).group(1)


def test_pyproject_uses_dynamic_version_from_package():
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert cfg["project"]["dynamic"] == ["version"]
    assert "version" not in cfg["project"], "静态 version 会和 __init__ 打架"
    assert cfg["tool"]["hatch"]["version"]["path"] == "src/jobradar/__init__.py"


def test_distribution_name_is_jobsearchradar():
    """PyPI 上 jobradar 与已有的 job-radar 太像、不可用，发布名是 jobsearchradar。"""
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert cfg["project"]["name"] == "jobsearchradar"
    # 命令行入口名保持不变（用户敲的还是 jobradar）
    assert cfg["project"]["scripts"]["jobradar"] == "jobradar.cli:main"
    assert cfg["project"]["scripts"]["jobradar-mcp"] == "jobradar.mcp_server:main"


def test_cli_version_matches_package_version():
    # stdin=DEVNULL：父进程 stdin 若是永不关闭的管道，子进程会挂在读输入上（见 test_entrypoints 注释）
    r = subprocess.run([sys.executable, "-m", "jobradar", "--version"],
                       capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr
    assert _init_version() in r.stdout, f"--version 输出 {r.stdout!r} 与 {_init_version()} 不一致"


def test_mcp_version_matches_package_version():
    r = subprocess.run([sys.executable, "-m", "jobradar.mcp_server", "--version"],
                       capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr
    assert _init_version() in r.stdout
