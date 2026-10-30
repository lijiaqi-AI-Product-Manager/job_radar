"""聚合补源通道探测：实习僧（shixiseng）。

只读公开页面，不登录、不破签名、不碰验证码。页面是 Nuxt SSR，岗位对象在
`window.__NUXT__=(function(...){...}(...))` 里，字段名被压缩成函数参数，因此用
node 求值后取 JSON，再做公司名归一匹配。结果写 work/agg_probe.jsonl。

用法：
  python work/agg_probe.py --limit 40 --pool all
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobradar.pipeline.calendar import match_targets  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
NUXT_JS = ROOT / "work" / "_nuxt_eval.js"
SUFFIX = re.compile(
    r"(股份有限公司|有限责任公司|有限公司|集团有限公司|集团|控股|中国|股份|总公司|公司)$"
)


def core(name: str) -> str:
    n = str(name).strip()
    for _ in range(3):
        n2 = SUFFIX.sub("", n)
        if n2 == n:
            break
        n = n2
    return n


def load_targets() -> dict:
    import yaml

    return yaml.safe_load((ROOT / "targets" / "top_companies.yaml").read_text(encoding="utf-8"))


def uncovered(limit: int = 0, pool: str = "all", offset: int = 0) -> list[str]:
    targets = load_targets()
    comp = {s.company for s in load_sources(ROOT / "sources")}
    matched = match_targets(targets, comp)
    sections = []
    if pool in ("all", "sector"):
        sections.extend(targets["sectors"].values())
    if pool in ("all", "province"):
        sections.extend((targets.get("provinces") or {}).values())
    names: list[str] = []
    seen = set()
    for group in sections:
        for n in group:
            n = str(n)
            if n in seen:
                continue
            seen.add(n)
            if not matched.get(n):
                names.append(n)
    return names[offset : offset + limit] if limit else names[offset:]


def eval_nuxt(html: str) -> dict | None:
    i = html.find("__NUXT__=")
    if i < 0:
        return None
    j = html.find("</script>", i)
    expr = html[i + len("__NUXT__=") : j].strip().rstrip(";")
    NUXT_JS.parent.mkdir(parents=True, exist_ok=True)
    NUXT_JS.write_text(
        "const v=" + expr + ";process.stdout.write(JSON.stringify(v));", encoding="utf-8"
    )
    try:
        out = subprocess.run(
            ["node", str(NUXT_JS)], capture_output=True, timeout=60, cwd=str(ROOT)
        )
    except Exception:  # noqa: BLE001
        return None
    if out.returncode != 0 or not out.stdout:
        return None
    try:
        return json.loads(out.stdout.decode("utf-8", "ignore"))
    except Exception:  # noqa: BLE001
        return None


def walk_jobs(o):
    if isinstance(o, dict):
        if "cname" in o and "uuid" in o:
            yield o
        for v in o.values():
            yield from walk_jobs(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk_jobs(v)


def probe(client: httpx.Client, company: str, pages: int = 1) -> dict:
    res = {"company": company, "engine": "shixiseng", "ok": False, "total": 0, "pages": []}
    names: list[str] = []
    try:
        for page in range(1, pages + 1):
            r = client.get(
                "https://www.shixiseng.com/interns",
                params={"keyword": company, "city": "全国", "type": "intern", "page": page},
            )
            res["status"] = r.status_code
            if r.status_code != 200:
                break
            d = eval_nuxt(r.text)
            if not d:
                break
            interns = None
            try:
                interns = d["data"][0]["interns"]
            except Exception:  # noqa: BLE001
                pass
            if not interns:
                break
            res["total"] = int(interns.get("total") or 0)
            jobs = list(walk_jobs(interns.get("data") or []))
            names.extend(str(j.get("cname") or "") for j in jobs)
            res["pages"].append(len(jobs))
            if res["total"] <= page * 20:
                break
    except Exception as exc:  # noqa: BLE001
        res["err"] = str(exc)[:160]
        return res
    names = [n for n in names if n]
    cc = core(company)
    extra_ok = ("集团", "科技", "游戏", "网络", "信息", "软件", "中国", "股份", "控股", "技术", "电子")
    exact = sorted(
        {
            n
            for n in names
            if core(n) == cc
            or (core(n).startswith(cc) and core(n)[len(cc) :] in extra_ok)
            or (cc.startswith(core(n)) and cc[len(core(n)) :] in extra_ok and len(core(n)) >= 2)
        }
    )
    res["names"] = sorted(set(names))[:15]
    res["n_jobs"] = len(names)
    res["hit"] = bool(exact)
    res["hit_names"] = exact[:6]
    res["ok"] = True
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--pool", default="all", choices=["all", "sector", "province"])
    ap.add_argument("--pages", type=int, default=1)
    ap.add_argument("--out", default="work/agg_probe.jsonl")
    ap.add_argument("--gap", type=float, default=1.0)
    args = ap.parse_args()

    names = uncovered(limit=args.limit, pool=args.pool, offset=args.offset)
    out = ROOT / args.out
    done = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    done.add(json.loads(line)["company"])
                except Exception:  # noqa: BLE001
                    pass
    names = [n for n in names if n not in done]
    hits = 0
    headers = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}
    with httpx.Client(headers=headers, follow_redirects=True, timeout=25) as client, out.open(
        "a", encoding="utf-8"
    ) as fh:
        for i, name in enumerate(names, 1):
            r = probe(client, name, pages=args.pages)
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            fh.flush()
            if r.get("hit"):
                hits += 1
            print(
                f"[{i}/{len(names)}] {name} total={r.get('total')} jobs={r.get('n_jobs')} hit={r.get('hit')} {r.get('hit_names') or ''}",
                flush=True,
            )
            time.sleep(args.gap)
    print(f"done: hit {hits}/{len(names)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
