# 查询引擎与采集适配器

**CLI · 9 个 MCP 工具 · 27 个适配器**

`jobradar/` 是安装包的源码。公开来源经适配器解析、归一化与入库，最终由本地 SQLite 查询层提供服务。

| 模块 | 内容 |
| :--- | :--- |
| `adapters/` | 平台与自研站适配器、限速、录制与回放 |
| `pipeline/` | 岗位入库、变更事件、招聘日历 |
| `core/queries.py` | CLI 与 MCP 共用的查询实现 |
| `store/` | SQLite 迁移、全文索引与 schema 校验 |
| `cli.py` / `mcp_server.py` | 命令行与 MCP stdio 入口 |
| `release_export.py` | 兼容既有客户端的数据库导出 |

主分支版本为 **2.0.0**。工作库支持 FTS5 trigram 索引，公开数据库保持兼容格式，新版客户端在本地建立索引。

安装与查询见 [项目首页](../README.md)，工程约束见 [开发规范](../docs/DEVELOPMENT.md)。
