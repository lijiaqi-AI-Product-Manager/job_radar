# 安装与数据渠道

核查日期：2026-11-03。代码版本、数据快照与镜像同步分别核实；搜索引擎缓存不作为当前版本依据。

| 渠道 | 当前状态 | 如何使用 |
| :--- | :--- | :--- |
| [PyPI](https://pypi.org/project/jobsearchradar/) | 2.2.1已从官方JSON与普通安装索引确认，独立环境复装、CLI/MCP通过 | 使用当前文档固定的发行版本 |
| [GitHub代码Release](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases) | 与PyPI分别核对版本及发行文件 | 下载源码包或wheel |
| [GitHub数据Release](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/tag/data-latest) | 按三库完整性清单分发；2026-11-03有新一代附件 | 执行 `jobradar update` |
| Gitee `qgauss/job_radar` | 公开仓库API和快照清单均返回404；最近一次同步在发布步骤失败 | 暂不作为可用镜像推荐 |
| npm | `jobsearchradar`、`jobradar`、`job_radar`三个名称的官方注册表均返回404 | 当前项目通过Python安装，不提供npm安装命令 |

以上npm核查仅覆盖列出的三个名称，不能据此推断所有作用域中的同类包。第三方同名项目也不能视为本项目发行版。

## Gitee恢复条件

镜像地址由仓库变量 `GITEE_REPO` 指定，本次确认其值为 `qgauss/job_radar`。
只有确认仓库存在、公开下载可用、发布凭据具有相应权限，并完成三库分片及整文件匿名SHA-256核验后，才能恢复可用声明。404不能单独区分仓库已删除、变为私有或地址变化。

`--mirror gitee` 保留为已有客户端参数；镜像不可用时客户端会尝试GitHub备用渠道。不要把回退下载成功记录成Gitee同步成功。默认命令已经使用GitHub，无需额外配置。

## 版本和时间

包版本不代表数据时间。查看 `jobradar --version` 确认代码，查看 `jobradar doctor` 或 `jobradar stats` 确认数据和来源观测时间。定时任务成功不保证每个来源都成功刷新。

正式安装和历史验证见[安装指南](INSTALLATION.md)；发布流程见[发布配置](PUBLISHING.md)。
