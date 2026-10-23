"""打包与入口点：安装成 wheel 之后仍然可用（这类问题只有在真装一遍时才暴露）。"""

import subprocess
import sys


def test_python_m_jobradar_works():
    """`python -m jobradar` 必须可用：没有 console script 的环境里这是唯一入口。

    回归背景：2026-10-23 用 wheel 装进干净 venv 才发现 `python -m jobradar` 报
    "No module named jobradar.__main__"——之前只有 `jobradar` 命令行入口。
    """
    r = subprocess.run([sys.executable, "-m", "jobradar", "--version"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "jobradar" in r.stdout.lower()
