# 给助手加一个求职搜索技能

让你常用的助手查询中国校招、实习、社招与招聘日历。求职者只需要说城市、方向和条件，助手调用工具、阅读岗位原文、整理候选与来源链接。

## 开始使用

在支持技能和本地工具的 Agent 工作模式中发送：

```text
请帮我接入这个仓库里的 jobradar 求职搜索技能：
https://github.com/lijiaqi-AI-Product-Manager/job_radar
先阅读接入说明，检查当前平台是否支持；完成后，帮我找上海的产品实习，列
出岗位要求、来源链接和已注明的截止日期，没写清的信息单独说明。
```

需要界面导入时，从[当前代码 Release](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/latest)下载 `jobradar-skill.zip`，或导入这里的 `jobradar` 文件夹。单独导入技能后，还需让助手按包内步骤准备工具与数据；完整说明见[第一次使用](../docs/GETTING-STARTED.md)和[平台接入](../docs/PLATFORMS.md)。

## 包含什么

| 文件 | 内容 |
| :--- | :--- |
| [查询工作流](jobradar/SKILL.md) | 根据自然语言需求选择搜索、详情、日历、变化、比较与趋势工具 |
| [首次准备](jobradar/references/setup.md) | 助手检查环境、安装工具、下载数据与验证接入 |
| [字段参考](jobradar/references/fields.md) | 岗位、招聘简章和日历的输出含义 |
| [个人条件与追问](jobradar/references/candidate-workflow.md) | 多城市、排除项、资格核实与连续修改条件 |
| [查询示例](jobradar/references/examples.md) | 常见需求与查询组合 |

Skill 告诉助手怎么查，MCP 让助手调用工具；两种方式共用查询规则。所有结果保留原始来源和数据时间，没写清的条件不当作不限，空结果也不能直接推断公司没有招聘。
