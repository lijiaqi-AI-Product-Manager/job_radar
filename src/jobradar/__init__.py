"""job_radar：中国校招/实习/社招岗位开放数据集（CLI / MCP / 库）。

版本号的**唯一来源**是这个文件：`pyproject.toml` 用 hatch 的动态版本读它，
CLI 和 MCP 的 `--version` 也读它。不要在这里之外再写死版本号（2026-10-24 踩过：
PyPI 发布名从 jobradar 改成 jobsearchradar 后，CLI 还在按旧 distribution 名查元数据，
--version 直接退回到 0.1.0）。
"""

__version__ = "1.12.1"
