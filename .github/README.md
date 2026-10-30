# 自动化与协作入口

**12 个工作流 · 2 类问题模板**

| 内容 | 用途 |
| :--- | :--- |
| `workflows/ci.yml` | Linux / Windows 与 Python 3.11 兼容、测试、合规和打包检查 |
| `workflows/daily.yml` | 定时采集、兼容数据库导出与数据快照 |
| `workflows/publish.yml` | 版本标签构建与已配置的包发布 |
| `workflows/mirror.yml` | 数据下载镜像同步 |
| 其余工作流 | 日历核验、样本录制、来源体检和查询评测 |
| `ISSUE_TEMPLATE/` | 可复现问题与公开来源补充 |
| `pull_request_template.md` | 变更、验证与来源证据 |

`main` 是面向用户的默认分支。代码版本标签使用 `vX.Y.Z`；`data-latest` 和 `data-archive` 独立分发数据。

版本流程见 [发布指南](../docs/PUBLISHING.md)，数据兼容要求见 [发布检查](../docs/RELEASE.md)。

网络体检、侦察和日历维护只在 main 对应输入变更或手动执行时启动；版本标签不会触发这些维护任务。代码测试与版本发布各自运行。
