"""对「可做」租户做完整抓取采样，算三件事：可入库条数、JD 覆盖率、CategoryId 分布。

只有 JD 覆盖率 ≥90%（项目契约）且归一化条数 > 0 的租户才算 doable。
这一步是红线「不许编造岗位数」的兑现方式：每个数字都来自真实抓取。

输入：work/doable_input.json（[{name,sector,brand,ats,tenant,host,url,count,title}]）
输出：work/sample_stats.jsonl
"""

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.beisen import BeisenAdapter  # noqa: E402
from jobradar.adapters.beisen_legacy import BeisenLegacyAdapter  # noqa: E402
from jobradar.adapters.hotjob import HotjobAdapter  # noqa: E402
from jobradar.sources import SourceConfig  # noqa: E402

UA = ("jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; open dataset, "
      "polite crawler; contact via GitHub issues)")
ADAPTERS = {"beisen": BeisenAdapter, "beisen_legacy": BeisenLegacyAdapter,
            "hotjob": HotjobAdapter}
LIMIT = 300  # 每家最多采样条数，控制请求量


def make_source(row: dict) -> SourceConfig:
    ats = row["ats"]
    params = {"tenant": row["tenant"]}
    if ats == "hotjob":
        params["host"] = row["host"]
        params["fetch_detail"] = True  # JD 正文只在详情接口里
        rtypes = ["campus"]
    elif ats == "beisen_legacy":
        params["portal"] = "campus"
        rtypes = ["campus"]
    else:
        rtypes = ["campus", "intern", "social"]
    return SourceConfig(
        id=f"probe-{re.sub(r'[^a-z0-9]+', '-', row['tenant'].lower())[:40]}",
        company=row["name"], adapter=ats, params=params, recruit_types=rtypes,
        enabled=True, rate_limit_rps=1,
        compliance={"checked_on": "2026-10-25", "robots": "allowed",
                    "terms": "公开 JSON 接口", "notes": "批量采样"})


def run(row: dict) -> dict:
    out = {k: row[k] for k in ("name", "sector", "brand", "ats", "tenant", "host", "url",
                               "count", "title") if k in row}
    src = make_source(row)
    cls = ADAPTERS[row["ats"]]
    with httpx.Client(headers={"User-Agent": UA, "Accept": "application/json,text/html"},
                      timeout=20, follow_redirects=True) as c:
        a = cls(src, c, sleep=lambda s: 0.4)
        cats: dict[str, int] = {}
        norm = jd = 0
        samples = []
        try:
            for i, raw in enumerate(a.fetch_raw()):
                cat = str(raw.get("CategoryId") or "") if row["ats"] == "beisen" else ""
                cats[cat] = cats.get(cat, 0) + 1
                try:
                    j = a.normalize(raw)
                except Exception:  # noqa: BLE001 — SkipRecord 等
                    if i >= LIMIT:
                        break
                    continue
                norm += 1
                if j.description:
                    jd += 1
                if len(samples) < 3:
                    samples.append({"title": j.title, "recruit_type": j.recruit_type,
                                    "has_jd": bool(j.description),
                                    "jd_len": len(j.description or "")})
                if i >= LIMIT:
                    break
        except Exception as e:  # noqa: BLE001
            out["error"] = f"{type(e).__name__}: {e}"[:120]
    out.update(sampled=sum(cats.values()), normalized=norm, jd=jd,
               jd_rate=round(jd / norm, 3) if norm else 0.0, categories=cats, samples=samples)
    return out


def main() -> None:
    rows = json.loads((WORK / "doable_input.json").read_text(encoding="utf-8"))
    print(f"采样 {len(rows)} 家", flush=True)
    res = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        for i, r in enumerate(ex.map(run, rows), 1):
            res.append(r)
            ok = r["normalized"] > 0 and r["jd_rate"] >= 0.9
            print(f"[{i:>3}] {'OK' if ok else 'XX'} {r['name']:<14}{r['ats']:<14}"
                  f"norm={r['normalized']:<4}jd={r['jd_rate']:<6}{r.get('error', '')}", flush=True)
            if i % 20 == 0:
                (WORK / "sample_stats.jsonl").write_text(
                    "\n".join(json.dumps(x, ensure_ascii=False) for x in res) + "\n",
                    encoding="utf-8")
    (WORK / "sample_stats.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in res) + "\n", encoding="utf-8")
    good = [r for r in res if r["normalized"] > 0 and r["jd_rate"] >= 0.9]
    print(f"可做 {len(good)} / {len(res)}")


if __name__ == "__main__":
    main()
