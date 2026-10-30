"""把验证通过的「飞书招聘 ATSX」门户写成 `sources/<slug>.yaml`（一家一文件，沿用 nio/xpeng 的写法）。

为什么一家一个文件：飞书站是**自研站**，`sources/` 的约定是「平台型进平台文件、自研站单独文件」
（见 docs/DEVELOPMENT.md 命名规范）。这里机械生成，避免手写 YAML 漏 compliance。

用法：`python3 work/add_feishu.py --in /tmp/exp/feishu_ok2.jsonl --apply`
每行是 `feishu_probe.py` 的输出：{company, base_url, website_path, count, jobs}
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TODAY = "2026-10-27"

# 公司名 → source id / 文件名 slug。没有现成的就按拼音近似；这里只收验证过的几家。
SLUG = {
    "MiniMax": "minimax",
    "中手游": "cmge",
    "中科创达": "thundersoft",
    "亚信安全": "asiainfo-sec",
    "仙工智能": "seer-group",
    "元气森林": "genki-forest",
    "出门问问": "mobvoi",
    "创梦天地": "idreamsky",
    "去哪儿": "qunar",
    "国民技术": "nsingtech",
    "塔斯汀": "tastien",
    "小马智行": "pony-ai",
}

TMPL = """id: {id}
company: {company}
adapter: feishu_atsx
recruit_types: [campus, intern]
rate_limit_rps: 1
params:
  base_url: "{base_url}"
  website_path: {path}
  portal_type: 3
  page_size: 100
  job_url: "{base_url}/{path}/position/{{id}}/detail"
compliance:
  checked_on: {today}
  robots: "none"            # {host}/robots.txt → 404（平台层无站点级规则）；只读公开列表，不触达 /referral
  terms: "飞书招聘 ATSX 门户：匿名 csrf token + 公开职位列表 JSON，无需登录、无验证码、无签名校验。token 只在内存中使用（docs/DEVELOPMENT.md 铁律 1）"
  notes: "2026-10-27 实测 count={count}，样本岗位「{sample}」；接口必须 POST，GET 会掉回 SPA 首页 HTML。"
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    made = 0
    for ln in Path(a.src).read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        if not r.get("ok"):
            continue
        comp = r["company"]
        sid = SLUG.get(comp) or re.sub(r"[^a-z0-9]+", "-", comp.lower()).strip("-")
        path = r["path"] if "path" in r else r["website_path"]
        p = ROOT / "sources" / f"{sid}.yaml"
        if p.exists():
            print(f"跳过已存在 {p.name}")
            continue
        body = TMPL.format(id=sid, company=comp, base_url=r["base_url"].rstrip("/"),
                           path=path, host=r["base_url"].split("//")[-1], count=r["count"],
                           sample=(r.get("jobs") or [""])[0], today=TODAY)
        print(f"{p.name}: {comp} {r['count']} 岗")
        if a.apply:
            p.write_text(body, encoding="utf-8")
            made += 1
    print(f"写入 {made} 个文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
