# 求职流程演示

流程演示采用真实工具结果节选，说明从求职条件到候选、资格核实和招聘日历的流程。流程画面由仓库脚本排版生成，不是第三方客户端录屏，不代表自然语言任务的端到端实测，也不代表查询耗时。

## 首页双语图

中英文README顶部使用两张同尺寸的双语图片：头图说明产品定位，合图紧凑展示四类招聘信息与对话查询流程。网页用图为1983×793的压缩JPEG，通过完整HTTPS地址加载，不进入Python源码包。

| 图片 | 内容 |
| :--- | :--- |
| [开场宣传 / Introduction](https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/job_radar/main/docs/assets/readme/hero-bilingual.jpg) | 给助手添加求职搜索技能，完成首次接入后用自然语言查询 |
| [机会与路径 / Opportunities and workflow](https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/job_radar/main/docs/assets/readme/features-bilingual.jpg) | 校招、实习、社招与招聘日历；说出需求、发现机会、核对来源 |

## 素材

| 文件 | 用途 |
| :--- | :--- |
| [流程GIF](assets/candidate-demo.gif) | README内直接查看，五个场景、约30秒循环 |
| [横版预览](assets/candidate-preview.png) | 视频封面和静态介绍 |
| [分享海报](assets/share-poster.jpg) | 1086×1448竖版，适合朋友圈与求职社群；搭配下方配文 |
| [仓库分享封面](assets/social-preview.png) | 1280×640的社交预览图片 |
| [结果节选](assets/candidate-demo-data.json) | 可追溯的查询条件、记录ID、原链接与数据时间 |

横版1920×1080、竖版1080×1920短片随[展示修订版Release](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/tag/v2.2.1)分发，视频不进入Python安装包。

## 分享配文

给常用的 AI 助手加了个“找工作”的技能：job_radar。覆盖中国校招、实习、社招和招聘日历，可以按城市、公司和方向查机会，读岗位原文、比较要求、找投递入口。

推荐在支持技能或本地工具的 Agent 工作模式里使用：先把仓库链接发给助手，让它引导接入，之后直接聊需求。WorkBuddy、千问办公可从技能导入开始；Kimi、Claude、ChatGPT 等具体路径见[平台说明](PLATFORMS.md)。

这段时间主要在打磨不显眼但重要的细节：公司别名、城市排除、重复信息、未知届次、过期日期、下载中断保护，以及字段与岗位原文冲突时的提醒。希望让找机会少一些来回翻站，也少一些误解。信息没写清就保留未知，投递前以原站为准。

复制[首次接入请求](GETTING-STARTED.md)即可开始。代码开源，欢迎分享给需要的朋友，也欢迎 Star。

仓库：https://github.com/lijiaqi-AI-Product-Manager/job_radar

## 五个场景

1. 求职者提出城市、方向、届次与排除条件。
2. 实际查询苏州/无锡财务校招、排除含上海的记录，保留2027届及届次未知候选。结果31个展示分组，画面仅列2个，不将分组数称为独立职位数。保留其他条件后31条记录中16条已标注届次、15条未知，字段有无不等于资格判定。
3. 独立查看交控科技北京软件岗位：已存学历为硕士，正文候选要求为本科；两者并列展示，需要回原页核实。此例不属于上一个城市查询的结果。
4. 按2026-11-03回查2027届秋招正式批：127条候选中4条有完整批次日期窗口、123条窗口未知。完整日期也不表示当前已确认接受投递。
5. 安装、下载、连接MCP/skill，然后开始对话查询。

查询于2026-11-03使用正式发行的2.2.0客户端执行。岗位快照截至 `2026-11-02T14:39:29Z`，日历截至 `2026-11-02T14:51:04Z`。源码中的结果节选与这些历史快照对应，不能作为实时在招承诺。

## 重新生成

素材制作环境需安装Pillow和可用的中文字体；生成MP4还需FFmpeg。普通用户使用查询工具无需安装这些依赖。

```bash
python scripts/make_showcase.py --video-dir .tmp/showcase
```

分享海报作为独立成品维护；此脚本不会覆盖它。默认从已提交的结果节选生成GIF、横版预览与 `candidate-flow-preview.png` 竖版流程预览，视频写到指定的临时目录。QR组件如可用则在本地生成真实仓库链接，无外部二维码服务；不可用时省略，不绘制装饰性假二维码。

原有的[CLI演示](assets/demo-zh.gif)继续保留，取自2026-10-29/30快照。CLI演示与流程示意都不模拟实时响应速度。
