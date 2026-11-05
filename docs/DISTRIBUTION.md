# 安装与数据渠道

分项核查日期见下表。代码版本、数据快照与镜像同步分别核实；搜索引擎缓存不作为当前版本依据。

| 渠道 | 当前状态 | 如何使用 |
| :--- | :--- | :--- |
| [PyPI](https://pypi.org/project/jobsearchradar/) | 2026-11-05核实2.3.2；官方普通索引全新安装、14项兼容检查与MCP九工具通过 | 按安装说明升级当前正式版 |
| [GitHub代码Release](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases) | 2026-11-05核实v2.3.2；wheel和源码包SHA-256与PyPI一致 | 下载源码包或wheel |
| [GitHub数据Release](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/tag/data-latest) | 2026-11-04核实原格式三库及无损精简正文；正式客户端真实下载通过 | 执行 `jobradar update` |
| Gitee `qgauss/job_radar` | 同步暂缓；最近公开入口核查仍为404，不作为当前可用渠道 | 暂不作为可用镜像推荐 |
| npm | `jobsearchradar`、`jobradar`、`job_radar`三个名称在2026-11-03核查的官方注册表均返回404 | 当前项目通过Python安装，不提供npm安装命令 |

以上npm核查仅覆盖列出的三个名称，不能据此推断所有作用域中的同类包。第三方同名项目也不能视为本项目发行版。

## Gitee恢复条件

Gitee同步暂缓；工作流仅在仓库变量`GITEE_MIRROR_ENABLED=true`时启用。此状态不影响GitHub数据下载和PyPI软件发布，不作为当前可用渠道推荐。

镜像地址由仓库变量 `GITEE_REPO` 指定，本次确认其值为 `qgauss/job_radar`。
只有确认仓库存在、公开下载可用、发布凭据具有相应权限，并完成三库分片及整文件匿名SHA-256核验后，才能恢复可用声明。404不能单独区分仓库已删除、变为私有或地址变化。

`--mirror gitee` 保留为已有客户端参数；镜像不可用时客户端会尝试GitHub备用渠道。不要把回退下载成功记录成Gitee同步成功。默认命令已经使用GitHub，无需额外配置。

同步任务先匿名检查公开仓库入口。缺少发布配置、仓库未公开或公开入口返回404时，报告“未执行同步”，跳过大文件下载和上传；这不计为镜像恢复或同步成功。网络超时、限流、服务错误及无效响应仍报告失败，不会用正常跳过掩盖。只有后续上传及完整匿名SHA-256验证完成，才算一次镜像发布成功。

## 版本和时间

包版本不代表数据时间。查看 `jobradar --version` 确认代码，查看 `jobradar doctor` 或 `jobradar stats` 确认数据和来源观测时间。定时任务成功不保证每个来源都成功刷新。

正式安装和历史验证见[安装指南](INSTALLATION.md)；发布流程见[发布配置](PUBLISHING.md)。
