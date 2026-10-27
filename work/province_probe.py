"""定向补省：对覆盖率低/零覆盖省份的目标公司做北森租户拼音探测 + 门户标题核归属。

只做「目标清单里没覆盖的公司」，命中的租户必须标题含中文公司名（或去掉后缀后一致）才算数，
避免又踩 `ys.zhiye.com` 这种共享门户。用法：python work/province_probe.py 甘肃 海南 [--write]
"""
from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
sys.path.insert(0, str(ROOT / "src"))

from jobradar.sources import load_sources  # noqa: E402

sys.path.insert(0, str(WORK))
from beisen_tenant_sweep import TENANT_DENY, candidates, probe  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
CORE = re.compile(r"(股份有限公司|有限责任公司|有限公司|集团控股|集团|控股|公司)$")


def core(name: str) -> str:
    return CORE.sub("", (name or "").strip())


def title_of(slug: str) -> str:
    try:
        with httpx.Client(headers=UA, follow_redirects=True, timeout=12) as c:
            r = c.get(f"https://{slug}.zhiye.com/")
        m = re.search(r"<title>(.*?)</title>", r.text, re.S)
        return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    except Exception:
        return ""


def main() -> None:
    provinces = [a for a in sys.argv[1:] if not a.startswith("--")]
    write = "--write" in sys.argv
    targets = yaml.safe_load((ROOT / "targets" / "top_companies.yaml").read_text(encoding="utf-8"))
    pinyin = json.loads((WORK / "pinyin_single.json").read_text(encoding="utf-8"))
    existing = load_sources(ROOT / "sources")
    have_key = {(s.adapter, str(s.params.get("tenant", "")).lower()) for s in existing}
    have_co = {core(s.company) for s in existing}

    todo: list[tuple[str, str]] = []
    for prov in provinces:
        for co in targets.get("provinces", {}).get(prov) or []:
            if core(co) in have_co:
                continue
            todo.append((prov, str(co)))
    print(f"待探公司 {len(todo)} 家（{'/'.join(provinces)}）")

    cands: list[tuple[str, str, str]] = []
    for prov, co in todo:
        for t in candidates(co, pinyin)[:6]:
            if t in TENANT_DENY or (("beisen"), t) in have_key:
                continue
            cands.append((prov, co, t))
    print(f"候选租户 {len(cands)} 个")

    hits: list[dict] = []

    def work(job: tuple[str, str, str]) -> None:
        prov, co, t = job
        try:
            with httpx.Client(headers=UA, timeout=12) as c:
                res = probe(c, t)
        except Exception:
            return
        if not res.get("ok") or int(res.get("count") or 0) <= 0:
            # 北森没命中时顺手试大易 / 飞书：两家的门户首页都能直接看标题
            for host, kind in ((f"https://{t}.hotjob.cn/", "hotjob"),
                               (f"https://{t}.jobs.feishu.cn/", "feishu_atsx")):
                try:
                    with httpx.Client(headers=UA, follow_redirects=True, timeout=12) as c2:
                        r2 = c2.get(host)
                except Exception:
                    continue
                if r2.status_code != 200:
                    continue
                m2 = re.search(r"<title>(.*?)</title>", r2.text, re.S)
                tt = re.sub(r"\s+", " ", m2.group(1)).strip() if m2 else ""
                if tt and core(co)[:2] in tt and "多品牌" not in tt and "共享" not in tt:
                    with lock:
                        hits.append({"province": prov, "company": co, "slug": t,
                                     "count": 0, "title": tt, "platform": kind})
            return
        title = title_of(t)
        if not title or "多品牌" in title or "共享" in title:
            return
        if core(co)[:2] not in title and core(co) not in title:
            return
        with lock:
            hits.append({"province": prov, "company": co, "slug": t,
                         "count": int(res["count"]), "title": title,
                         "platform": "beisen"})

    from threading import Lock
    lock = Lock()
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(work, cands))
    print(f"命中 {len(hits)}")
    for h in sorted(hits, key=lambda x: -x["count"]):
        print(f'  {h["province"]:<4}{h["slug"]:<20}{h["company"][:16]:<18}{h["count"]:>5}  {h["title"][:34]}')
    if write and hits:
        with open(WORK / "province_hits.jsonl", "a", encoding="utf-8") as fh:
            for h in hits:
                fh.write(json.dumps({**h}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
