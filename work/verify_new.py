"""把探针结果（/tmp/exp/par*.jsonl、/tmp/exp/site1.jsonl）核验成可落地的源配置。

核验原则（**不猜、不编**）：
  - 门户必须自报公司名：飞书读 `tenant_info.tenant_name` / `<title>`，北森读门户 title，
    大易读门户 title；名字和候选公司对得上（主体名互相包含）才收。
  - 岗位数只认接口返回的 `count`/`positonNum`，不按首页「工程师」字样估算。
  - 已经在 `sources/` 里的租户直接跳过（避免重复抓同一批岗位）。

输出：
  /tmp/exp/todo.yaml   —— 待人工并入 sources/ 的片段（按适配器分组）
  /tmp/exp/todo.json   —— 同样内容的机器可读版
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "work"))
sys.path.insert(0, str(ROOT / "scripts"))

import ats_par as ap  # noqa: E402

from jobradar.adapters.base import USER_AGENT  # noqa: E402

NOISE = ("股份有限公司", "有限责任公司", "有限公司", "集团", "控股", "科技", "技术",
         "（中国）", "(中国)", "中国", "公司", "国际")


def core(name: str) -> str:
    n = name
    for w in NOISE:
        n = n.replace(w, "")
    return n.strip() or name


def same(a: str, b: str) -> bool:
    ca, cb = core(a), core(b)
    return bool(ca and cb and (ca in cb or cb in ca))


def existing_tenants() -> tuple[set[str], set[str], set[str]]:
    beisen: set[str] = set()
    hotjob: set[str] = set()
    feishu: set[str] = set()
    for p in Path(ROOT / "sources").glob("*.yaml"):
        txt = p.read_text(encoding="utf-8")
        if p.name.startswith("beisen"):
            beisen.update(re.findall(r"tenant:\s*([A-Za-z0-9_\-]+)", txt))
        elif p.name.startswith("hotjob"):
            hotjob.update(re.findall(r"tenant:\s*([A-Za-z0-9_\-]+)", txt))
        elif "adapter: feishu_atsx" in txt:
            m = re.search(r"base_url:\s*\"?https://([a-z0-9\-]+)\.jobs\.feishu\.cn", txt)
            if m:
                feishu.add(m.group(1))
    return beisen, hotjob, feishu


def feishu_identity(cli: httpx.Client, slug: str) -> tuple[str, str]:
    """飞书门户自报的公司名与页面 title。"""
    ap._feishu_throttle()
    try:
        r = cli.get(f"https://{slug}.jobs.feishu.cn/")
    except Exception:  # noqa: BLE001
        return "", ""
    if r.status_code != 200:
        return "", ""
    title = ""
    m = re.search(r"<title>(.*?)</title>", r.text or "", re.I | re.S)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()
    name = ""
    mm = re.search(r'js-websiteInfo" type="text/json">(.*?)</script>', r.text or "", re.S)
    if mm:
        try:
            name = (json.loads(mm.group(1)).get("tenant_info") or {}).get("tenant_name") or ""
        except Exception:  # noqa: BLE001
            name = ""
    return name, title


def portal_title(cli: httpx.Client, url: str) -> str:
    try:
        r = cli.get(url)
    except Exception:  # noqa: BLE001
        return ""
    m = re.search(r"<title>(.*?)</title>", r.text or "", re.I | re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def main() -> int:
    beisen_have, hot_have, fei_have = existing_tenants()
    print(f"已有：北森 {len(beisen_have)} / 大易 {len(hot_have)} / 飞书 {len(fei_have)}")

    seen: set[tuple[str, str]] = set()
    out: dict[str, list[dict]] = {"beisen": [], "hotjob": [], "feishu_atsx": [], "self": [],
                                  "nuxt": []}

    # 1) ATS 探针结果
    for f in sorted(Path("/tmp/exp").glob("par*.jsonl")):
        for ln in f.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(ln)
            except Exception:  # noqa: BLE001
                continue
            for pr in rec.get("found") or []:
                ats, tenant, cnt = pr["ats"], pr["tenant"], pr.get("count", -1)
                key = (ats, tenant)
                if key in seen:
                    continue
                if ats == "beisen" and tenant in beisen_have:
                    continue
                if ats == "hotjob" and tenant in hot_have:
                    continue
                if ats in ("feishu", "feishu-host") and tenant in fei_have:
                    continue
                if cnt == 0:
                    continue
                seen.add(key)
                out.setdefault(ats, []).append(
                    {"company": rec["company"], "tenant": tenant, "count": cnt,
                     "src": f.name})

    # 2) 官网→ATS 结果
    sp = Path("/tmp/exp/site1.jsonl")
    if sp.exists():
        for ln in sp.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(ln)
            except Exception:  # noqa: BLE001
                continue
            ats = rec.get("ats")
            if ats not in ("beisen", "hotjob", "feishu_atsx", "self", "nuxt"):
                continue
            tenant = rec.get("tenant") or rec.get("host") or ""
            key = (ats, tenant)
            if key in seen or (ats == "beisen" and tenant in beisen_have) or \
                    (ats == "hotjob" and tenant in hot_have) or \
                    (ats == "feishu_atsx" and tenant in fei_have):
                continue
            seen.add(key)
            out[ats].append({"company": rec["company"], "tenant": tenant,
                             "host": rec.get("host", ""), "entry": rec.get("entry", ""),
                             "conf": rec.get("conf", ""), "count": -1, "src": "site1"})

    # 3) 逐个核验门户自报的名字
    ok: dict[str, list[dict]] = {k: [] for k in out}
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=12.0,
                      follow_redirects=True) as cli:
        for ats, rows in out.items():
            for r in rows:
                t = r["tenant"]
                if ats == "feishu_atsx":
                    name, title = feishu_identity(cli, t)
                    r["portal_name"], r["title"] = name, title
                    r["verified"] = bool(name or title) and same(r["company"], name or title)
                elif ats == "beisen":
                    # 北森门户首屏就是公司名，用 title 核对
                    title = portal_title(cli, f"https://{t}.zhiye.com/")
                    r["title"] = title
                    r["verified"] = bool(title) and same(r["company"], title)
                elif ats == "hotjob":
                    title = portal_title(cli, f"https://{t}.hotjob.cn/")
                    r["title"] = title
                    r["verified"] = bool(title) and same(r["company"], title)
                else:
                    r["verified"] = True   # self/nuxt 已在 site_ats 里做过归属校验
                if r["verified"]:
                    ok[ats].append(r)
                else:
                    print(f"REJECT {ats:10s} {t:24s} {r['company']:12s} "
                          f"-> title={r.get('title', '')[:30]!r} name={r.get('portal_name', '')!r}")

    total = sum(len(v) for v in ok.values())
    print(f"\n核验通过 {total} 条：" + ", ".join(f"{k}={len(v)}" for k, v in ok.items() if v))
    Path("/tmp/exp/todo.json").write_text(json.dumps(ok, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    lines = []
    for ats, rows in ok.items():
        if not rows:
            continue
        lines.append(f"# ==== {ats} ({len(rows)})")
        for r in sorted(rows, key=lambda x: -(x.get("count") or 0)):
            lines.append(f"- {ats:10s} {r['company']:14s} tenant={r['tenant']:26s} "
                         f"count={r['count']:<6} title={(r.get('title') or r.get('conf') or '')[:34]}")
    Path("/tmp/exp/todo.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
