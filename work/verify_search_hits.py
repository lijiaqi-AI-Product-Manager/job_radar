"""按公司名搜索到的门户 → 逐条探活 + 用门户 <title> 定归属。

输入 work/company_search.jsonl（每行 {company, engine, query, hosts:[...]}）
输出 work/search_verified.jsonl（platform/slug/tenant/host/company/title/count）

- *.zhiye.com        → 北森探针（子域就是租户）
- *.jobs.feishu.cn   → 飞书探针（csrf 换 token + 根页 <title>）
- *.hotjob.cn        → 先取首页找 SU 租户 id，再用大易探针
"""
from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "work"))
from verify_tenants_found import beisen_probe, core, feishu_probe, hotjob_probe  # noqa: E402

SRC = ROOT / "work" / "company_search.jsonl"
OUT = ROOT / "work" / "search_verified.jsonl"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"}
SU_RE = re.compile(r"SU[0-9a-fA-F]{20,}")


CITY = ("石家庄", "秦皇岛", "乌鲁木齐", "呼和浩特", "哈尔滨", "内蒙古", "黑龙江", "北京", "上海", "天津", "重庆",
        "河北", "山西", "辽宁", "吉林", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
        "广东", "广西", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "宁夏", "新疆", "西藏",
        "唐山", "保定", "邯郸", "石家庄", "青岛", "烟台", "苏州", "无锡", "常州", "杭州", "宁波", "温州",
        "合肥", "福州", "厦门", "泉州", "南昌", "济南", "郑州", "洛阳", "武汉", "长沙", "广州", "深圳",
        "佛山", "东莞", "珠海", "南宁", "桂林", "成都", "绵阳", "贵阳", "昆明", "西安", "兰州", "银川",
        "长春", "沈阳", "大连", "西宁", "太原", "南京")


def brand(name: str) -> str:
    """去掉城市/省份前缀与公司后缀，只留品牌词。"""
    s = core(name or "")
    for c in CITY:
        if s.startswith(c) and len(s) > len(c):
            s = s[len(c):]
            break
    return s


def title_ok(title: str, company: str) -> bool:
    t, c = brand(title), brand(company)
    return bool(t and c) and (c in t or t in c) and len(c) >= 2


def one(cli: httpx.Client, host: str, company: str) -> dict | None:
    host = host.lower().strip()
    try:
        if host.endswith(".zhiye.com"):
            slug = host[: -len(".zhiye.com")]
            r = beisen_probe(cli, slug)
            return {"platform": "beisen", "slug": slug, "host": host, **r}
        if host.endswith(".jobs.feishu.cn"):
            slug = host[: -len(".jobs.feishu.cn")]
            r = feishu_probe(cli, slug)
            return {"platform": "feishu_atsx", "slug": slug, "host": host, **r}
        if host.endswith(".hotjob.cn"):
            home = cli.get(f"https://{host}/", timeout=20.0, follow_redirects=True)
            su = SU_RE.search(home.text or "")
            if not su:
                return {"platform": "hotjob", "slug": host, "host": host, "count": 0, "title": "", "no_su": True}
            tenant = su.group(0)
            r = hotjob_probe(cli, tenant)
            return {"platform": "hotjob", "slug": tenant, "host": host, **r}
    except Exception as e:  # noqa: BLE001
        return {"platform": "err", "slug": host, "host": host, "company": company,
                "error": f"{type(e).__name__}: {e}"[:100]}
    return None


def main() -> int:
    rows = [json.loads(ln) for ln in SRC.read_text(encoding="utf-8").splitlines() if ln.strip()]
    seen: dict[str, str] = {}
    for r in rows:
        for h in r.get("hosts") or []:
            seen.setdefault(str(h).lower(), r["company"])
    tasks = [(h, c) for h, c in seen.items() if any(h.endswith(x) for x in (".zhiye.com", ".jobs.feishu.cn", ".hotjob.cn"))]
    print("待探", len(tasks), flush=True)
    kept, bad, err = [], 0, 0
    with httpx.Client(headers=UA, timeout=20.0, follow_redirects=True) as cli, ThreadPoolExecutor(8) as ex:
        for i, (res, (host, company)) in enumerate(zip(ex.map(lambda t: one(cli, *t), tasks), tasks, strict=False), 1):
            if not res:
                continue
            res["company"] = res.get("company") or company
            if res.get("error"):
                err += 1
            elif int(res.get("count") or 0) <= 0:
                err += 1
            elif not title_ok(res.get("title") or "", company):
                bad += 1
                print(f"REJ {host[:30]:<30} {company[:10]:<10} title={str(res.get('title'))[:24]}", flush=True)
            else:
                kept.append(res)
                print(f"OK  {res['platform']:<11} {str(res.get('slug'))[:26]:<26} {company[:10]:<10} "
                      f"{res.get('count'):>5} {str(res.get('title'))[:18]}", flush=True)
            if i % 40 == 0:
                print(f"--- {i}/{len(tasks)} keep={len(kept)} rej={bad} err={err}", flush=True)
    OUT.write_text("".join(json.dumps(k, ensure_ascii=False) + "\n" for k in kept), encoding="utf-8")
    print(f"完成 {len(tasks)}：保留 {len(kept)}、标题不符 {bad}、空/异常 {err}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
