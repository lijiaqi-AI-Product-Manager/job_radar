# fixtures 录制计划（2026-10-26）

目的：给每个**接口型**源留一份可回放的脱敏响应，CI 不联网也能跑通适配器契约测试。
只读公开接口，录制时按 1 rps 串行；不录任何需要登录、签名或验证码的接口。

## 1. 录制范围

- 全量可做公司：**855** 家
- 已有结构化采样（可立即录制）：**116** 家
- 按招聘系统分布：`beisen` 102、`unknown` 9、`none` 3、`self_hosted` 2

其余公司为自行实现的官网投递页（`self_hosted` / `unknown`），页面结构各异，
不进 fixtures，走 `tests/test_calendar_entries.py` 的日历字段校验即可。

## 2. 录制命令

```bash
python scripts/record_fixtures.py <source_id> --max-pages 1
```

## 3. 优先级（按实测在招岗位数降序）

| # | 公司 | host | 系统 | 在招(Count) | 采样 | JD 覆盖 |
|---|---|---|---|---|---|---|
| 1 | 来伊份 | `laiyifen.zhiye.com` | `beisen` | 7216 | 301 | 100% |
| 2 | 追觅科技 | `dreame.zhiye.com` | `beisen` | 2199 | 301 | 100% |
| 3 | 传音控股非洲 | `transsion.zhiye.com` | `beisen` | 985 | 301 | 100% |
| 4 | 货拉拉 | `huolala.zhiye.com` | `beisen` | 532 | 301 | 100% |
| 5 | 凯莱英 | `asymchem.zhiye.com` | `beisen` | 424 | 301 | 100% |
| 6 | 豪迈科技 | `himile.zhiye.com` | `beisen` | 408 | 301 | 100% |
| 7 | 国金证券 | `gjzq.zhiye.com` | `beisen` | 403 | 301 | 100% |
| 8 | 长安汽车 | `changan.zhiye.com` | `beisen` | 375 | 301 | 100% |
| 9 | 金风科技 | `goldwind.zhiye.com` | `beisen` | 347 | 301 | 100% |
| 10 | 北方华创 | `career.naura.com` | `self_hosted` | 322 | 301 | 100% |
| 11 | 白象食品 | `baixiangfood.zhiye.com` | `beisen` | 297 | 297 | 100% |
| 12 | 东方希望 | `easthope1.zhiye.com` | `beisen` | 278 | 278 | 100% |
| 13 | 宇信科技 | `yusys-campus.zhiye.com` | `beisen` | 278 | 278 | 100% |
| 14 | 德方纳米 | `dynanonic.zhiye.com` | `beisen` | 257 | 257 | 100% |
| 15 | 潍柴动力 | `weichaidongli.zhiye.com` | `beisen` | 246 | 246 | 100% |
| 16 | 蒙牛 | `mengniu.zhiye.com` | `beisen` | 211 | 211 | 100% |
| 17 | 南芯科技 | `nanxin.zhiye.com` | `beisen` | 205 | 205 | 100% |
| 18 | 北森控股 | `beisen.zhiye.com` | `beisen` | 194 | 194 | 100% |
| 19 | 拓荆科技 | `piotech.cn` | `unknown` | 194 | 194 | 100% |
| 20 | 海柔创新 | `hairobotics.zhiye.com` | `beisen` | 169 | 169 | 100% |
| 21 | 晶合集成 | `nexchip.zhiye.com` | `beisen` | 165 | 165 | 100% |
| 22 | 阅文集团 | `campus.yuewen.com` | `unknown` | 138 | 138 | 100% |
| 23 | 江波龙 | `longsys.zhiye.com` | `beisen` | 129 | 129 | 100% |
| 24 | 山东威高 | `weigao.zhiye.com` | `beisen` | 127 | 127 | 100% |
| 25 | 民泰银行 | `mintaibank.zhiye.com` | `beisen` | 122 | 122 | 100% |
| 26 | 石头科技 | `roborock.zhiye.com` | `beisen` | 113 | 113 | 100% |
| 27 | 双汇 | `shuanghui.zhiye.com` | `beisen` | 107 | 107 | 100% |
| 28 | 百胜中国 | `yumchina.zhiye.com` | `beisen` | 105 | 96 | 100% |
| 29 | 博腾股份 | `porton.zhiye.com` | `beisen` | 103 | 103 | 100% |
| 30 | 深南电路 | `scc.zhiye.com` | `beisen` | 93 | 93 | 100% |
| 31 | 大华会计师 | `dahuacpa.zhiye.com` | `beisen` | 92 | 92 | 100% |
| 32 | 芯海科技 | `chipsea.zhiye.com` | `beisen` | 90 | 90 | 100% |
| 33 | 华峰集团 | `huafeng.zhiye.com` | `beisen` | 86 | 86 | 99% |
| 34 | 宇树Unitree | `unitree.zhiye.com` | `beisen` | 86 | 86 | 100% |
| 35 | 优艾智合 | `youibot1.zhiye.com` | `beisen` | 85 | 85 | 100% |
| 36 | 国元证券 | `gyzq.zhiye.com` | `beisen` | 85 | 85 | 100% |
| 37 | 叮咚买菜 | `ddmc.zhiye.com` | `beisen` | 84 | 84 | 100% |
| 38 | 诺诚健华 | `innocare.zhiye.com` | `beisen` | 83 | 83 | 100% |
| 39 | 劲仔食品 | `jinzaifood.zhiye.com` | `beisen` | 74 | 74 | 100% |
| 40 | 爱旭股份 | `aikosolar.com` | `unknown` | 70 | 70 | 100% |
| 41 | 盐津铺子 | `www.yanjinpuzi.com` | `unknown` | 70 | 70 | 100% |
| 42 | 埃夫特 | `efort.zhiye.com` | `beisen` | 68 | 68 | 100% |
| 43 | 新宙邦 | `www.capchem.com` | `unknown` | 65 | 65 | 100% |
| 44 | 国联水产 | `glsc.zhiye.com` | `beisen` | 63 | 63 | 100% |
| 45 | 思必驰 | `aispeech.zhiye.com` | `beisen` | 62 | 62 | 100% |
| 46 | 昆仑芯 | `kunlunxin.zhiye.com` | `beisen` | 62 | 62 | 100% |
| 47 | H&M中国 | `hm.zhiye.com` | `beisen` | 59 | 59 | 100% |
| 48 | 梅卡曼德 | `mechmind.zhiye.com` | `beisen` | 57 | 57 | 100% |
| 49 | 奥乐齐中国 | `aldichina.zhiye.com` | `beisen` | 55 | 55 | 100% |
| 50 | 宝宝巴士 | `babybus.zhiye.com` | `beisen` | 55 | 55 | 100% |
| 51 | 中文在线 | `zhongwenzaixian.zhiye.com` | `beisen` | 54 | 54 | 100% |
| 52 | 德邦快递 | `deppon.zhiye.com` | `beisen` | 52 | 52 | 100% |
| 53 | 创维 | `www.skyworthdigital.com` | `unknown` | 50 | 108 | 100% |
| 54 | 认养一头牛 | `ryytn.zhiye.com` | `beisen` | 50 | 50 | 100% |
| 55 | 启明星辰 | `venustech.zhiye.com` | `beisen` | 48 | 48 | 100% |
| 56 | 图达通 | `seyond.zhiye.com` | `beisen` | 47 | 47 | 100% |
| 57 | 东吴证券 | `dwzq.zhiye.com` | `beisen` | 46 | 46 | 100% |
| 58 | 迈瑞动物医疗 | `mindrayanimal.zhiye.com` | `beisen` | 46 | 46 | 100% |
| 59 | 浙商证券 | `zszq.zhiye.com` | `beisen` | 45 | 44 | 100% |
| 60 | 芯碁微装 | `cfmee.zhiye.com` | `beisen` | 44 | 44 | 100% |
| 61 | 东山精密 | `dsbj.zhiye.com` | `beisen` | 41 | 41 | 100% |
| 62 | 云知声 | `unisound.zhiye.com` | `beisen` | 39 | 39 | 100% |
| 63 | 节卡机器人 | `jaka.zhiye.com` | `beisen` | 39 | 39 | 100% |
| 64 | 新松机器人 | `siasun.zhiye.com` | `beisen` | 37 | 37 | 100% |
| 65 | 思念食品 | `synear.zhiye.com` | `beisen` | 33 | 33 | 100% |
| 66 | 绿联 | `ugreen.zhiye.com` | `beisen` | 31 | 31 | 100% |
| 67 | 得一微电子 | `yeestor.zhiye.com` | `beisen` | 30 | 30 | 100% |
| 68 | 精测电子 | `jingce.zhiye.com` | `beisen` | 30 | 26 | 100% |
| 69 | 郎酒 | `langjiu3.zhiye.com` | `beisen` | 30 | 30 | 100% |
| 70 | 大润发 | `rt-mart.zhiye.com` | `beisen` | 29 | 29 | 100% |
| 71 | 赣锋锂业 | `ganfenglithium.zhiye.com` | `beisen` | 29 | 29 | 100% |
| 72 | 观远数据 | `guandata.zhiye.com` | `beisen` | 26 | 26 | 100% |
| 73 | vivo | `hr-campus.vivo.com` | `unknown` | 25 | 25 | 100% |
| 74 | 概伦电子 | `primarius.zhiye.com` | `beisen` | 25 | 25 | 100% |
| 75 | 九牧王 | `joeone.zhiye.com` | `beisen` | 24 | 24 | 100% |
| 76 | 明略科技 | `mininglamp.zhiye.com` | `beisen` | 24 | 24 | 100% |
| 77 | 东风日产 | `dongfengnissan.zhiye.com` | `beisen` | 21 | 21 | 100% |
| 78 | 爱慕 | `aimer.zhiye.com` | `beisen` | 21 | 21 | 100% |
| 79 | 视比特机器人 | `speedbot.zhiye.com` | `beisen` | 18 | 18 | 100% |
| 80 | 华海清科 | `hwatsing1.zhiye.com` | `beisen` | 17 | 17 | 100% |
| 81 | 现代牧业 | `xiandaimuye.zhiye.com` | `beisen` | 17 | 17 | 100% |
| 82 | 益禾堂 | `yihetang.zhiye.com` | `beisen` | 17 | 17 | 100% |
| 83 | 天融信 | `topsec.zhiye.com` | `beisen` | 15 | 15 | 100% |
| 84 | 宁德新能源 | `zhaopin.atlbattery.com` | `self_hosted` | 15 | 43 | 100% |
| 85 | 内外 | `neiwai.zhiye.com` | `beisen` | 14 | 14 | 100% |
| 86 | 华峰测控 | `accotest.zhiye.com` | `beisen` | 13 | 13 | 100% |
| 87 | 海正药业 | `hisunpharm.zhiye.com` | `beisen` | 13 | 13 | 100% |
| 88 | 中国化学工程 | `job.zzu.edu.cn` | `none` | 12 | 301 | 100% |
| 89 | 云南白药 | `job.zzu.edu.cn` | `none` | 12 | 34 | 100% |
| 90 | 固德威 | `job.xidian.edu.cn` | `none` | 12 | 44 | 100% |
| 91 | 良品铺子 | `lppz.zhiye.com` | `beisen` | 12 | 12 | 100% |
| 92 | 通威 | `tongwei.zhiye.com` | `beisen` | 12 | 12 | 100% |
| 93 | 通威股份 | `tongwei.zhiye.com` | `beisen` | 12 | 12 | 100% |
| 94 | 中科星图 | `geovis.zhiye.com` | `beisen` | 11 | 11 | 100% |
| 95 | 合思 | `hosecloud.zhiye.com` | `beisen` | 11 | 11 | 100% |
| 96 | 神策数据 | `sensorsdata.zhiye.com` | `beisen` | 11 | 11 | 100% |
| 97 | 长江证券 | `cjzq.zhiye.com` | `beisen` | 11 | 11 | 100% |
| 98 | 今麦郎 | `jmlzp.zhiye.com` | `beisen` | 10 | 10 | 100% |
| 99 | 澳优乳业 | `www.ausnutria.com` | `unknown` | 10 | 15 | 100% |
| 100 | 仙琚制药 | `xjzy.zhiye.com` | `beisen` | 9 | 9 | 100% |
| 101 | 沛嘉医疗 | `peijiamedical.zhiye.com` | `beisen` | 8 | 8 | 100% |
| 102 | 瀚高数据库 | `highgo.zhiye.com` | `beisen` | 8 | 8 | 100% |
| 103 | 每刻报销 | `maycur.zhiye.com` | `beisen` | 7 | 7 | 100% |
| 104 | Manner咖啡 | `mannercoffee.zhiye.com` | `beisen` | 6 | 6 | 100% |
| 105 | 中国航空研究院 | `zghkyjy.zhiye.com` | `beisen` | 6 | 6 | 100% |
| 106 | 东软医疗 | `neusoftmedical.zhiye.com` | `beisen` | 4 | 4 | 100% |
| 107 | 中集集团 | `www.cimc.cn` | `unknown` | 4 | 4 | 100% |
| 108 | 艾力斯 | `allist.zhiye.com` | `beisen` | 4 | 4 | 100% |
| 109 | 长江养老 | `cjpension1.zhiye.com` | `beisen` | 4 | 4 | 100% |
| 110 | 丸美 | `marubi.zhiye.com` | `beisen` | 3 | 3 | 100% |
| 111 | 创新奇智 | `ainnovation.zhiye.com` | `beisen` | 3 | 3 | 100% |
| 112 | 江淮汽车 | `jac.zhiye.com` | `beisen` | 3 | 3 | 100% |
| 113 | 聚辰股份 | `giantec.zhiye.com` | `beisen` | 3 | 3 | 100% |
| 114 | 北新建材 | `bnbm.zhiye.com` | `beisen` | 2 | 2 | 100% |
| 115 | 阿道夫 | `adolph.zhiye.com` | `beisen` | 2 | 2 | 100% |
| 116 | 贝因美 | `beingmate.zhiye.com` | `beisen` | 1 | 1 | 100% |

## 4. 脱敏要求

- 响应里的企业联系人电话 / 邮箱一律替换为 `REDACTED`；
- 候选人相关的任何字段（投递记录、简历）不属于公开列表接口，不在录制范围；
- 录制产物只保留前 1 页，避免仓库膨胀。
