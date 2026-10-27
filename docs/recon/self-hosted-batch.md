# 自研招聘站：能接的与不能接的（2026-10-26 批量探测）

## 为什么单独一页

`companies.jsonl` 里 1,014 家公司，按 ATS 分成：北森 387（已在抓）、大易 26（已在抓）、
自研站 128、飞书 ATSX 33、Moka 28、其他/未知 407。**继续挖北森已经不划算**（见
[batch-report 附录 A](../internal/PROGRESS-2026-10-24.md)），增量只能从自研站来。

但自研站 128 家，每一家的接口都不一样。逐个逆向签名不现实，也违反项目红线
（不逆向加密/签名）。所以先做一次**批量筛**：只读首页 + 首屏里的候选接口路径，
纯粹看「有没有一个不用破就能拿的公开 JSON」。

脚本：`scripts/probe_json_endpoints.py`（1 req/s，只 GET，不带 Cookie，不伪造 UA）。

## 判定口径

| 信号 | 含义 |
|---|---|
| 页面 200 + content-type 含 `json` | 页面本身就是数据接口，最省事 |
| 页面 200，HTML 里能找到 `/api/*` 且返回 JSON | 有公开数据接口，值得写适配器 |
| 页面 200，但候选路径全是 404 / 返回 HTML | 前端把数据塞在 SSR 的 `__NUXT__` / `__NEXT_DATA__` 里，要单独处理 |
| 403 / ERR ConnectError | 有 WAF 或站点不在境内可达范围，记 blocked，不绕 |

## 结果（117 个未配源的自研站）

本轮探测覆盖 `companies.jsonl` 中 `ats=self_hosted` 且尚未建源的 117 家。**绝大多数返回的
是前端框架的 SSR 骨架**（`--` 行），页面能开、但没有可直接消费的列表接口 —— 这类要写
「解析 `__NEXT_DATA__` / 首屏 props」的适配器，属于「能做但每家一个」的工作量。

真正探测到公开 JSON 的站点另行记录，并通过 `docs/recon/<company>.md` 单独留档。

## 已确认可以做的（按收益排序）

| 站点 | 形态 | 说明 |
|---|---|---|
| `jobs.siemens.com.cn/siemens/position/index` | SSR + 2 个 JSON 接口 | 西门子中国校招；接口返回岗位列表，无需签名 |
| `campus.tcl.com` | 待写适配器 | TCL 校招，当前 `jd_status=blocked`，实际是前端加密参数，暂不碰 |
| `campus.pony.ai` | 待确认 | 小马智行，SPA |
| `join.tencentmusic.com` | 待确认 | 腾讯音乐，与腾讯主站不同源 |

## 明确不做（记录原因，避免以后重复投入）

| 站点 | 原因 | 证据 |
|---|---|---|
| `app.mokahr.com`（28 家） | 前端签名，需要逆向 | [moka.md](moka.md) |
| 飞书 ATSX（33 家） | 需要 `x-atsx-*` 签名头 | [atsx.md](atsx.md) |
| 华为 `career.huawei.com` | WAF 对接口路径返回 403 | [blocked.jsonl](../../blocked.jsonl) `waf_403` |
| 各站 `403` / DNS 不可达 | 站点侧限制，不做任何绕过 | 本页探测日志 |

## 复现

```bash
python3 - <<'EOF'
import json
comps = [json.loads(l) for l in open("companies.jsonl")]
todo = {c["careers_url"]: c["company"]
        for c in comps if c.get("ats") == "self_hosted" and c.get("careers_url")}
json.dump(todo, open("/tmp/probe_sites.json", "w"), ensure_ascii=False)
EOF
PYTHONPATH=src python3 scripts/probe_json_endpoints.py /tmp/probe_sites.json /tmp/probe_result.json
```
