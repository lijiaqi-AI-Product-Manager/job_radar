"""第二轮 slug 穷举：用公司简称（去地名/去行业后缀）+ 长尾后缀，补第一轮漏掉的租户。

第一轮只试「全名拼音 / 品牌英文 / 首字母」，漏掉了大量真实租户（如 youzan、
huazhu1 这种「品牌拼音 + 数字」）。这一轮把简称也纳入：
  杭州海康威视数字技术 → 海康威视 → haikangweishi / hikvision ...
"""

import json
import re
import sys
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import httpx  # noqa: E402
from fast_sweep import probe_beisen, probe_beisen_legacy, probe_hotjob  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
UA = ("jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; open dataset, "
      "polite crawler; contact via GitHub issues)")

try:
    from pypinyin import Style, lazy_pinyin
except ImportError:  # pragma: no cover
    raise SystemExit("需要 pypinyin") from None

DROP_PREFIX = ("中国", "上海", "北京", "深圳", "广州", "杭州", "江苏", "浙江", "广东", "山东",
               "苏州", "南京", "天津", "重庆", "成都", "武汉", "西安", "合肥", "宁波", "青岛")
DROP_SUFFIX = ("股份有限公司", "有限责任公司", "有限公司", "集团", "控股", "股份", "科技",
               "技术", "实业", "投资", "发展", "控股集团")


def short_names(name: str, brand: str) -> list[str]:
    out = [name]
    s = name
    for p in DROP_PREFIX:
        if s.startswith(p) and len(s) > len(p) + 1:
            s = s[len(p):]
            break
    for suf in DROP_SUFFIX:
        s = s.replace(suf, "")
    if s and s != name:
        out.append(s)
    if brand:
        out.append(brand)
    return out


def slug_set(name: str, brand: str) -> list[str]:
    out: list[str] = []

    def add(x: str) -> None:
        x = re.sub(r"[^a-z0-9-]", "", x.lower())
        if x and 2 <= len(x) <= 28 and x not in out:
            out.append(x)

    for n in short_names(name, brand):
        py = "".join(lazy_pinyin(n, style=Style.NORMAL))
        ini = "".join(lazy_pinyin(n, style=Style.FIRST_LETTER))
        for base in (py, ini):
            add(base)
            for suf in ("1", "2", "hr", "zp", "zhaopin", "rc", "job"):
                add(base + suf)
    return out[:14]


DONE: set[str] = set()


def work_item(item: tuple[str, str, str]) -> dict | None:
    name, sector, brand = item
    if name in DONE:  # 已确认可做的跳过，省请求
        return None
    with httpx.Client(headers={"User-Agent": UA, "Accept": "application/json,text/html"},
                      timeout=10, follow_redirects=True) as c:
        tried = []
        for s in slug_set(name, brand):
            tried.append(s)
            for fn in (probe_beisen, probe_hotjob, probe_beisen_legacy):
                hit = fn(c, s, name)
                if hit:
                    return {"company": name, "sector": sector, "brand": brand,
                            "tried": tried, **hit}
    return None


def main(items: Iterable[tuple[str, str, str]]) -> None:
    items = [i for i in items if i[0] not in DONE]
    print(f"待探测 {len(items)} 家", flush=True)
    hits = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=10) as ex:
        for i, r in enumerate(ex.map(work_item, items), 1):
            if r:
                hits.append(r)
                print(f"[{i}] {'OK' if r['name_match'] else '??'} {r['company']:<14}"
                      f"{r['ats']:<14}{r['tenant']:<22}{r['count']:>6}  {r['title'][:24]}",
                      flush=True)
            if i % 100 == 0:
                el = time.time() - t0
                print(f"... {i}/{len(items)} 命中 {len(hits)} {el:.0f}s "
                      f"({i / el * 60:.0f}/分)", flush=True)
                (WORK / "round2_hits.jsonl").write_text(
                    "\n".join(json.dumps(x, ensure_ascii=False) for x in hits) + "\n",
                    encoding="utf-8")
    (WORK / "round2_hits.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in hits) + "\n", encoding="utf-8")
    print(f"完成：命中 {len(hits)} / {len(items)}，{time.time() - t0:.0f}s")


if __name__ == "__main__":
    stats = [json.loads(x) for x in
             (WORK / "sample_stats_all.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    DONE.update(r["name"] for r in stats if r["normalized"] > 0 and r["jd_rate"] >= 0.9)
    print(f"跳过已确认可做 {len(DONE)} 家", flush=True)
    rows = []
    for line in (WORK / "candidates_clean.tsv").read_text(encoding="utf-8").splitlines():
        p = line.split("\t")
        if len(p) >= 3:
            rows.append((p[0], p[1], p[2]))
    main(rows)
