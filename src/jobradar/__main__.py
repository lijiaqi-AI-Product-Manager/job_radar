"""让 `python -m jobradar` 也能用（等价于 `jobradar` 命令）。

以库方式安装时没有 `jobradar` 可执行文件的环境（比如某些 CI 的 `python -m` 调用、
或用户只 pip install 了 wheel），这个入口是唯一能跑 CLI 的方式。
"""

from jobradar.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
