"""打包与入口点：安装成 wheel 之后仍然可用（这类问题只有在真装一遍时才暴露）。"""

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_python_m_jobradar_works():
    """`python -m jobradar` 必须可用：没有 console script 的环境里这是唯一入口。

    回归背景：2026-10-23 用 wheel 装进干净 venv 才发现 `python -m jobradar` 报
    "No module named jobradar.__main__"——之前只有 `jobradar` 命令行入口。
    """
    # stdin 显式给 DEVNULL：父进程 stdin 若是「永不关闭的管道」（后台任务、部分 CI/沙箱），
    # 子进程会一直等输入，在 capture_output 下表现为挂住 60s+（2026-10-27 实测）。
    r = subprocess.run([sys.executable, "-m", "jobradar", "--version"],
                       capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr
    assert "jobradar" in r.stdout.lower()


def test_mcp_server_prints_help_instead_of_hanging():
    """`jobradar-mcp --help` 必须立刻返回说明。

    回归背景：MCP 入口以前直接 `server.run()`，`--help` 会挂在 stdio 上，
    用户配 MCP 客户端时完全不知道自己命令写对没有。
    """
    r = subprocess.run([sys.executable, "-m", "jobradar.mcp_server", "--help"],
                       capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr
    assert "MCP" in r.stdout


def test_company_aliases_are_forced_into_the_wheel():
    """wheel 必须带 taxonomy/company_aliases.yaml。

    回归背景：`taxonomy/` 在仓库根，不在 `src/jobradar` 下，hatch 默认不会打包；
    pip 装完就没有简称映射（「中核」查不到「中国核工业集团」），而测试跑在源码树里是绿的。
    """
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    force = cfg["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    src = next(k for k in force if k.endswith("company_aliases.yaml"))
    assert (ROOT / src).exists(), f"force-include 的源文件不存在：{src}"
    assert force[src].endswith("jobradar/_data/company_aliases.yaml")


def test_aliases_load_from_package_data_when_repo_taxonomy_missing(tmp_path, monkeypatch):
    """模拟 wheel 安装：仓库根没有 taxonomy/ 时，要能从包内 `_data` 读到映射表。"""
    from jobradar import aliases

    data = tmp_path / "_data"
    data.mkdir()
    shutil.copy(ROOT / "taxonomy" / "company_aliases.yaml", data / "company_aliases.yaml")
    (tmp_path / "nope.yaml").unlink(missing_ok=True)
    monkeypatch.setattr(aliases, "_candidates",
                        lambda: (tmp_path / "nope.yaml", data / "company_aliases.yaml"))
    aliases._aliases.cache_clear()
    try:
        assert aliases.match_names("中核") == ["中核", "中国核工业集团"]
    finally:
        aliases._aliases.cache_clear()
