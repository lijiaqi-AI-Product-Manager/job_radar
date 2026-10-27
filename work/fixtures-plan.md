# fixtures 录制计划（本批 122 家）

目的：给每个新增源留一份可回放的脱敏响应，CI 里不联网也能过 `tests/test_adapter_contract.py`。

## 1. 录制命令

```bash
# 单源录制（默认列表第 1 页 + 该页岗位详情，1 rps）
python scripts/record_fixtures.py <source_id> --max-pages 1
```

## 2. 优先级（按在招岗位数降序，先录前 30 家）

| # | source_id | 公司 | 适配器 | 在招(Count) | JD 覆盖 |
|---|---|---|---|---|---|
| 1 | `beisen-laiyifen` | 来伊份 | `beisen` | 7216 | 100% |
| 2 | `beisen-dreame` | 追觅科技 | `beisen` | 2199 | 100% |
| 3 | `beisen-transsion-2` | 传音控股非洲 | `beisen` | 985 | 100% |
| 4 | `beisen-zhonghuan` | 中环股份 | `beisen` | 759 | 100% |
| 5 | `beisen-huolala-2` | 货拉拉 | `beisen` | 532 | 100% |
| 6 | `beisen-asymchem` | 凯莱英 | `beisen` | 424 | 100% |
| 7 | `beisen-himile` | 豪迈科技 | `beisen` | 408 | 100% |
| 8 | `beisen-gjzq-2` | 国金证券 | `beisen` | 403 | 100% |
| 9 | `beisen-changanqiche-2` | 长安汽车 | `beisen` | 375 | 100% |
| 10 | `beisen-goldwind` | 金风科技 | `beisen` | 347 | 100% |
| 11 | `beisen-bfhc` | 北方华创 | `beisen` | 322 | 100% |
| 12 | `beisen-baixiangfood` | 白象食品 | `beisen` | 297 | 100% |
| 13 | `beisen-yusys` | 宇信科技 | `beisen` | 278 | 100% |
| 14 | `beisen-easthope1` | 东方希望 | `beisen` | 278 | 100% |
| 15 | `beisen-dynanonic` | 德方纳米 | `beisen` | 257 | 100% |
| 16 | `beisen-weichaidongli` | 潍柴动力 | `beisen` | 246 | 100% |
| 17 | `beisen-mengniu-2` | 蒙牛 | `beisen` | 211 | 100% |
| 18 | `beisen-nanxin-2` | 南芯科技 | `beisen` | 205 | 100% |
| 19 | `beisen-piotech` | 拓荆科技 | `beisen` | 194 | 100% |
| 20 | `beisen-beisen-2` | 北森控股 | `beisen` | 194 | 100% |
| 21 | `beisen-hairobotics-2` | 海柔创新 | `beisen` | 169 | 100% |
| 22 | `beisen-nexchip-2` | 晶合集成 | `beisen` | 165 | 100% |
| 23 | `beisen-dobot` | 越疆科技 | `beisen` | 143 | 100% |
| 24 | `beisen-yuewen-2` | 阅文集团 | `beisen` | 138 | 100% |
| 25 | `beisen-longsys` | 江波龙 | `beisen` | 129 | 100% |
| 26 | `beisen-weigao` | 山东威高 | `beisen` | 127 | 100% |
| 27 | `beisen-mintaibank` | 民泰银行 | `beisen` | 122 | 100% |
| 28 | `beisen-roborock-2` | 石头科技 | `beisen` | 113 | 100% |
| 29 | `beisen-shuanghui-2` | 双汇 | `beisen` | 107 | 100% |
| 30 | `beisen-legacy-yumchina` | 百胜中国 | `beisen_legacy` | 105 | 100% |

## 3. 全量清单

剩余 92 家的录制顺序同上（按 Count 降序）：

```
python scripts/record_fixtures.py beisen-porton --max-pages 1
python scripts/record_fixtures.py beisen-scc --max-pages 1
python scripts/record_fixtures.py beisen-dahuacpa --max-pages 1
python scripts/record_fixtures.py beisen-chipsea --max-pages 1
python scripts/record_fixtures.py beisen-huafeng-2 --max-pages 1
python scripts/record_fixtures.py beisen-unitree --max-pages 1
python scripts/record_fixtures.py beisen-youibot1 --max-pages 1
python scripts/record_fixtures.py beisen-gyzq-2 --max-pages 1
python scripts/record_fixtures.py beisen-ddmc --max-pages 1
python scripts/record_fixtures.py beisen-innocare --max-pages 1
python scripts/record_fixtures.py beisen-jinzaifood --max-pages 1
python scripts/record_fixtures.py beisen-aikosolar --max-pages 1
python scripts/record_fixtures.py beisen-yanjinpuzi --max-pages 1
python scripts/record_fixtures.py beisen-efort --max-pages 1
python scripts/record_fixtures.py beisen-capchem --max-pages 1
python scripts/record_fixtures.py beisen-glsc --max-pages 1
python scripts/record_fixtures.py beisen-kunlunxin1 --max-pages 1
python scripts/record_fixtures.py beisen-aispeech --max-pages 1
python scripts/record_fixtures.py beisen-hm --max-pages 1
python scripts/record_fixtures.py beisen-mechmind --max-pages 1
python scripts/record_fixtures.py beisen-aldichina --max-pages 1
python scripts/record_fixtures.py beisen-babybus --max-pages 1
python scripts/record_fixtures.py beisen-zhongwenzaixian --max-pages 1
python scripts/record_fixtures.py beisen-deppon --max-pages 1
python scripts/record_fixtures.py beisen-edan --max-pages 1
python scripts/record_fixtures.py hotjob-su668b8b251c240e2e76ea71d8 --max-pages 1
python scripts/record_fixtures.py beisen-ryytn-2 --max-pages 1
python scripts/record_fixtures.py beisen-venustech --max-pages 1
python scripts/record_fixtures.py beisen-seyond --max-pages 1
python scripts/record_fixtures.py beisen-mindrayanimal --max-pages 1
python scripts/record_fixtures.py beisen-dwzq-2 --max-pages 1
python scripts/record_fixtures.py beisen-legacy-zszq --max-pages 1
python scripts/record_fixtures.py beisen-cfmee --max-pages 1
python scripts/record_fixtures.py hotjob-su68fb2499b7da1347a9dd852c --max-pages 1
python scripts/record_fixtures.py beisen-dsbj-2 --max-pages 1
python scripts/record_fixtures.py beisen-jaka --max-pages 1
python scripts/record_fixtures.py beisen-unisound --max-pages 1
python scripts/record_fixtures.py beisen-siasun-2 --max-pages 1
python scripts/record_fixtures.py beisen-synear-2 --max-pages 1
python scripts/record_fixtures.py beisen-ugreen-2 --max-pages 1
python scripts/record_fixtures.py beisen-yeestor --max-pages 1
python scripts/record_fixtures.py beisen-legacy-jingce-2 --max-pages 1
python scripts/record_fixtures.py beisen-langjiu-2 --max-pages 1
python scripts/record_fixtures.py beisen-rt-mart --max-pages 1
python scripts/record_fixtures.py beisen-ganfenglithium --max-pages 1
python scripts/record_fixtures.py beisen-guandata --max-pages 1
python scripts/record_fixtures.py beisen-primarius --max-pages 1
python scripts/record_fixtures.py beisen-vivo --max-pages 1
python scripts/record_fixtures.py beisen-joeone --max-pages 1
python scripts/record_fixtures.py beisen-mininglamp --max-pages 1
python scripts/record_fixtures.py beisen-dongfengnissan --max-pages 1
python scripts/record_fixtures.py beisen-aimer-2 --max-pages 1
python scripts/record_fixtures.py beisen-speedbot --max-pages 1
python scripts/record_fixtures.py beisen-hwatsing --max-pages 1
python scripts/record_fixtures.py beisen-xiandaimuye --max-pages 1
python scripts/record_fixtures.py beisen-yihetang --max-pages 1
python scripts/record_fixtures.py beisen-topsec --max-pages 1
python scripts/record_fixtures.py hotjob-su5ff30f5b9b0d78e6f4283a0b --max-pages 1
python scripts/record_fixtures.py beisen-neiwai --max-pages 1
python scripts/record_fixtures.py beisen-accotest --max-pages 1
python scripts/record_fixtures.py beisen-hisun --max-pages 1
python scripts/record_fixtures.py beisen-tongwei-2 --max-pages 1
python scripts/record_fixtures.py hotjob-su630a3a0e2f9d2406b4f6c5f1 --max-pages 1
python scripts/record_fixtures.py hotjob-su62c3b55d2f9d241e4c8e260f --max-pages 1
python scripts/record_fixtures.py hotjob-su69294dabe3842960d1a72594 --max-pages 1
python scripts/record_fixtures.py beisen-tongwei-3 --max-pages 1
python scripts/record_fixtures.py hotjob-su6136b970bef57c3b638162c4 --max-pages 1
python scripts/record_fixtures.py beisen-lppz-2 --max-pages 1
python scripts/record_fixtures.py beisen-geovis --max-pages 1
python scripts/record_fixtures.py beisen-sensorsdata --max-pages 1
python scripts/record_fixtures.py beisen-hosecloud --max-pages 1
python scripts/record_fixtures.py beisen-cjzq-2 --max-pages 1
python scripts/record_fixtures.py hotjob-su66f3c75a6202cc1a0cba3202 --max-pages 1
python scripts/record_fixtures.py beisen-legacy-jmlzp --max-pages 1
python scripts/record_fixtures.py beisen-xjzy --max-pages 1
python scripts/record_fixtures.py beisen-peijiamedical --max-pages 1
python scripts/record_fixtures.py beisen-highgo --max-pages 1
python scripts/record_fixtures.py beisen-legacy-maycur --max-pages 1
python scripts/record_fixtures.py beisen-mannercoffee --max-pages 1
python scripts/record_fixtures.py beisen-legacy-zghkyjy-2 --max-pages 1
python scripts/record_fixtures.py hotjob-su63e34a270dcad474881066a5 --max-pages 1
python scripts/record_fixtures.py beisen-cjpension1 --max-pages 1
python scripts/record_fixtures.py beisen-neusoftmedical --max-pages 1
python scripts/record_fixtures.py beisen-legacy-allist --max-pages 1
python scripts/record_fixtures.py hotjob-su652251308ac1ca0dbbc521c3 --max-pages 1
python scripts/record_fixtures.py beisen-giantec --max-pages 1
python scripts/record_fixtures.py beisen-jac --max-pages 1
python scripts/record_fixtures.py beisen-legacy-ainnovation --max-pages 1
python scripts/record_fixtures.py beisen-legacy-marubi --max-pages 1
python scripts/record_fixtures.py beisen-bnbm --max-pages 1
python scripts/record_fixtures.py beisen-adolph --max-pages 1
python scripts/record_fixtures.py beisen-legacy-beingmate --max-pages 1
```

## 4. 回放契约

- fixtures 落 `tests/fixtures/<source_id>/page1.json`（或 `.html`），命名与 `record_fixtures.py` 一致
- 冻结前先跑 `PYTHONPATH=src python -m pytest tests/test_adapter_contract.py -q`
- 禁止把带时间戳/随机参数的 URL 写进 fixture 键（会让回放失效，见 hotjob 适配器注释）
