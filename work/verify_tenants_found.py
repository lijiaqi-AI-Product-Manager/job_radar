"""把「搜到的租户」变成「可入库的源」：验证活着、确认归属、量出岗位数。

输入（都是上一轮探测的产物，可叠加）：
  work/search_tenants.jsonl   360 搜索命中（自带门户标题，归属证据最强）
  work/careers_ats.jsonl      招聘官网反查命中（标题要现抓）

输出：work/verified_new_sources.jsonl，一行一个候选，字段：
  company   匹配到的目标公司名（无匹配则 null）
  score     归属置信度 0~1
  kind      beisen / hotjob / feishu_atsx / workday / beisen_host
  params    直接可写进 sources YAML 的 params
  count     在招岗位数（hotjob/feishu 可能是 null）
  title     门户标题
  evidence  判定依据（标题命中 / 拼音命中 / 仅岗位数）

红线：只读公开门户首页与公开列表接口，同 host ≥1.05s，不翻页。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from jobradar.adapters.base import USER_AGENT  # noqa: E402

OUT = ROOT / "work" / "verified_new_sources.jsonl"
UA = {"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"}
BEISEN = "/api/Jobad/GetJobAdPageList"
BODY = {"PageIndex": 0, "PageSize": 3, "KeyWords": "", "SpecialType": 0, "PortalId": "",
        "DisplayFields": ["LocNames", "PostDate"]}
SUFFIX = re.compile(r"(股份有限公司|有限责任公司|有限公司|集团|控股|中国|股份|总公司|公司)$")
PUNCT = re.compile(r"[（）()·\s\-—.。,]")
_lock = threading.Lock()
_last: dict[str, float] = {}


def throttle(host: str) -> None:
    while True:
        with _lock:
            wait = _last.get(host, 0.0) + 1.05 - time.time()
            if wait <= 0:
                _last[host] = time.time()
                return
        time.sleep(min(wait, 0.4))


def core(name: str) -> str:
    n = PUNCT.sub("", name or "")
    prev = None
    while prev != n:
        prev = n
        n = SUFFIX.sub("", n)
    return n


def load_targets() -> list[tuple[str, str]]:
    """(公司名, 行业) —— 以 targets/top_companies.yaml 的两段清单为准。"""
    import yaml

    d = yaml.safe_load((ROOT / "targets" / "top_companies.yaml").read_text(encoding="utf-8"))
    out: list[tuple[str, str]] = []
    for sector, names in (d.get("sectors") or {}).items():
        for n in names:
            out.append((n, sector))
    for prov, names in (d.get("provinces") or {}).items():
        for n in names:
            out.append((n, f"省域·{prov}"))
    return out


def beisen_probe(cli: httpx.Client, slug: str) -> dict:
    host = f"{slug}.zhiye.com"
    throttle(host)
    try:
        page = cli.get(f"https://{host}/", timeout=12.0)
        title = ""
        m = re.search(r"<title[^>]*>(.*?)</title>", page.text, re.S | re.I)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip()
        throttle(host)
        r = cli.post(f"https://{host}{BEISEN}", json=BODY, timeout=12.0)
        d = r.json() if r.text.lstrip().startswith("{") else {}
        count = int(d.get("Count") or 0)
        if d.get("Code") != 200:
            return {"ok": False, "title": title, "kind": "beisen", "reason": f"code={d.get('Code')}"}
        return {"ok": count > 0, "title": title, "count": count, "kind": "beisen",
                "params": {"tenant": slug}}
    except (httpx.HTTPError, ValueError) as e:
        return {"ok": False, "kind": "beisen", "reason": type(e).__name__}


def hotjob_probe(cli: httpx.Client, slug: str) -> dict:
    host = f"{slug}.hotjob.cn"
    throttle(host)
    try:
        r = cli.get(f"https://{host}/", timeout=12.0)
    except httpx.HTTPError as e:
        return {"ok": False, "kind": "hotjob", "reason": type(e).__name__}
    if r.status_code != 200:
        return {"ok": False, "kind": "hotjob", "reason": f"http{r.status_code}"}
    m = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.S | re.I)
    title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    su = re.search(r"(SU[0-9a-f]{20,})", str(r.url) + " " + r.text[:8000], re.I)
    return {"ok": bool(su), "title": title, "kind": "hotjob", "count": None,
            "params": {"host": host, "tenant": su.group(1) if su else ""}}


FEISHU_TITLE_TAIL = re.compile(
    r"[\s\-–—|｜]+(?:社会招聘|校园招聘|实习招聘|实习生招聘|招聘官网|官方招聘|招聘|社招|校招|首页)+$"
)


def feishu_probe(cli: httpx.Client, slug: str) -> dict:
    """feishu ATSX：根路径 200 且 `<title>` 形如「NIO蔚来-社会招聘」，标题就是公司名金矿。

    2026-10-27 实测 nio → `NIO蔚来-社会招聘`、anker-in → `加入安克创新`；csrf token 只用来确认租户活着。
    """
    host = f"{slug}.jobs.feishu.cn"
    throttle(host)
    try:
        page = cli.get(f"https://{host}/", timeout=12.0)
        m = re.search(r"<title[^>]*>(.*?)</title>", page.text, re.S | re.I)
        title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    except httpx.HTTPError as e:
        return {"ok": False, "kind": "feishu_atsx", "reason": type(e).__name__}
    thumb = FEISHU_TITLE_TAIL.sub("", title)
    thumb = re.sub(r"^(?:加入|欢迎加入|欢迎来到)", "", thumb).strip()
    throttle(host)
    try:
        r = cli.post(f"https://{host}/api/v1/csrf/token", json={"portal_entrance": 1},
                     headers={**UA, "Accept": "application/json"}, timeout=12.0)
        d = r.json() if r.text.lstrip().startswith("{") else {}
    except (httpx.HTTPError, ValueError) as e:
        return {"ok": False, "kind": "feishu_atsx", "reason": type(e).__name__}
    token = ((d.get("data") or {}).get("token")) or ""
    return {"ok": bool(token), "kind": "feishu_atsx", "count": None, "title": thumb,
            "params": {"tenant": slug}}


PROBES = {"beisen": beisen_probe, "hotjob": hotjob_probe, "feishu_atsx": feishu_probe}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    targets = load_targets()
    cores = [(core(n), n, s) for n, s in targets]
    cands: dict[tuple[str, str], dict] = {}

    st = ROOT / "work" / "search_tenants.jsonl"
    if st.exists():
        for ln in st.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            platform = str(r.get("platform") or "").lower()
            kind = {"zhiye": "beisen", "beisen": "beisen", "hotjob": "hotjob",
                    "jobs": "feishu_atsx", "feishu": "feishu_atsx",
                    "feishu_atsx": "feishu_atsx"}.get(platform)
            if not kind:
                continue
            key = (kind, r["slug"])
            cur = cands.get(key)
            # 同一租户多条命中时保留标题最长的那条（更像「XX招聘官网」）
            if cur is None or len(r.get("title") or "") > len(cur.get("title") or ""):
                cands[key] = {"kind": kind,
                              "slug": r["slug"], "title": r.get("title") or "",
                              "desc": r.get("desc") or "", "query": r.get("query"), "src": "search"}
    ca = ROOT / "work" / "careers_ats.jsonl"
    if ca.exists():
        for ln in ca.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            f = r.get("found") or {}
            kind = f.get("kind")
            if kind in ("moka_blocked", None, "none", "hotjob_probable"):
                continue
            slug = f.get("slug") or ""
            if kind == "beisen_host":
                key = ("beisen_host", f.get("host") or "")
                cands.setdefault(key, {"kind": "beisen_host", "slug": f.get("host"),
                                       "host": f.get("host"), "title": f.get("title") or "",
                                       "desc": "", "query": None, "src": "careers",
                                       "company_hint": r.get("company")})
                continue
            if kind == "workday":
                continue
            if not slug or slug in {"www", "wecruit", "portal-oss"}:
                continue
            key = (kind, slug)
            cands.setdefault(key, {"kind": kind, "slug": slug, "title": f.get("title") or "",
                                   "desc": "", "query": None, "src": "careers",
                                   "company_hint": r.get("company")})

    sh = ROOT / "work" / "so360_hosts.txt"
    if sh.exists():
        for ln in sh.read_text(encoding="utf-8").splitlines():
            if "\t" not in ln:
                continue
            kind, host = ln.split("\t", 1)
            kind = kind.strip()
            host = host.strip().lower()
            if kind == "beisen":
                cands.setdefault(("beisen", host), {"kind": "beisen", "slug": host,
                                                    "title": "", "desc": "", "query": None,
                                                    "src": "so360"})
            elif kind == "hotjob":
                cands.setdefault(("hotjob", host), {"kind": "hotjob", "slug": host,
                                                    "title": "", "desc": "", "query": None,
                                                    "src": "so360"})
            elif kind == "feishu":
                cands.setdefault(("feishu_atsx", host), {"kind": "feishu_atsx", "slug": host,
                                                         "title": "", "desc": "", "query": None,
                                                         "src": "so360"})
            # workday / tupu360 需要额外参数（site、租户域名），本轮先跳过

    ch = ROOT / "work" / "cc_hosts.tsv"
    if ch.exists():
        kmap = {"beisen": "beisen", "hotjob": "hotjob", "feishu": "feishu_atsx"}
        for ln in ch.read_text(encoding="utf-8").splitlines():
            parts = ln.split("\t")
            if len(parts) < 2:
                continue
            kind = kmap.get(parts[0].strip())
            host = parts[1].strip().lower()
            if not kind or not host:
                continue
            cands.setdefault((kind, host), {"kind": kind, "slug": host, "title": "",
                                            "desc": "", "query": None, "src": "commoncrawl"})

    os_hosts = ROOT / "work" / "osint_hosts.tsv"
    if os_hosts.exists():
        kmap = {"beisen": "beisen", "hotjob": "hotjob", "feishu": "feishu_atsx"}
        for ln in os_hosts.read_text(encoding="utf-8").splitlines():
            parts = ln.split("\t")
            if len(parts) < 2:
                continue
            kind = kmap.get(parts[0].strip())
            host = parts[1].strip().lower()
            if not kind or not host:
                continue
            cands.setdefault((kind, host), {"kind": kind, "slug": host, "title": "",
                                            "desc": "", "query": None, "src": "osint"})

    tp = ROOT / "work" / "tenant_probe2.jsonl"
    if tp.exists():
        for ln in tp.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            kind = {"hotjob": "hotjob", "feishu": "feishu_atsx"}.get(r.get("platform"))
            slug = (r.get("slug") or "").lower()
            if not kind or not slug:
                continue
            cands.setdefault((kind, slug), {"kind": kind, "slug": slug,
                                            "title": r.get("title") or "", "desc": "",
                                            "query": None, "src": "nameprobe",
                                            "company_hint": r.get("company_guess")})

    todo = list(cands.values())
    if a.limit:
        todo = todo[: a.limit]
    print(f"候选 {len(todo)}，目标 {len(targets)}，并发 {a.workers}", flush=True)

    done: set[str] = set()
    if OUT.exists():
        for ln in OUT.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(ln)
                done.add(f"{d['kind']}:{d.get('params', {}).get('tenant') or d.get('params', {}).get('host')}")
            except Exception:  # noqa: BLE001
                pass

    def work(c: dict) -> dict:
        kind = c["kind"]
        slug = c["slug"]
        key = f"{kind}:{slug}"
        if key in done:
            return {"skip": True}
        with httpx.Client(headers=UA, follow_redirects=True, timeout=15.0) as cli:
            if kind == "beisen_host":
                host = c["host"]
                throttle(host)
                try:
                    r = cli.post(f"https://{host}{BEISEN}", json=BODY, timeout=12.0)
                    d = r.json() if r.text.lstrip().startswith("{") else {}
                except (httpx.HTTPError, ValueError):
                    return {"skip": True}
                count = int(d.get("Count") or 0)
                if d.get("Code") != 200 or count <= 0:
                    return {"skip": True}
                res = {"ok": True, "title": c["title"], "count": count, "kind": "beisen",
                       "params": {"tenant": host.split(".")[0], "host": host}}
            else:
                probe = PROBES[kind]
                res = probe(cli, slug)
                if not res.get("ok"):
                    return {"skip": True}
        title = res.get("title") or c.get("title") or ""
        hay = PUNCT.sub("", title + c.get("desc", ""))
        best = (0.0, None, None)
        for cc, name, sector in cores:
            if not cc:
                continue
            if cc and cc in hay:
                score = 0.95 if len(cc) >= 3 else 0.7
            elif cc in slug or cc.replace("中国", "") in slug:
                score = 0.75
            else:
                continue
            if score > best[0]:
                best = (score, name, sector)
        hint = c.get("company_hint")
        if hint and best[1] is None:
            hc = core(hint)
            if hc and (hc in hay or hc in slug):
                best = (0.8, hint, "careers 反查")
        return {"company": best[1], "score": best[0], "sector": best[2], "kind": kind,
                "params": res["params"], "count": res.get("count"), "title": title,
                "slug": slug, "src": c["src"], "query": c.get("query"),
                "evidence": ("标题命中" if best[0] >= 0.9 else
                             "拼音/提示命中" if best[0] >= 0.7 else "无归属")}

    t0 = time.time()
    n_new = 0
    with OUT.open("a", encoding="utf-8") as f, ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(work, c): c for c in todo}
        for i, fut in enumerate(futs, 1):
            rec = fut.result()
            if rec.get("skip"):
                continue
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            n_new += 1
            if rec.get("company"):
                print(f"[{i}] {rec['company']:12s} {rec['kind']:11s} "
                      f"{rec['params'].get('tenant') or rec['params'].get('host')} "
                      f"count={rec.get('count')} score={rec['score']:.2f} {rec['title'][:30]}", flush=True)
            if i % 50 == 0:
                print(f"... {i}/{len(todo)} {time.time() - t0:.0f}s 存活 {n_new}", flush=True)
    print(f"完成：存活候选 {n_new}，用时 {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
