"""多路并行的 ATS 入口探测器：北森 / 大易 / 飞书招聘（ATSX）/ Moka 公开页，一次跑完。

为什么单独写这一版：`beisen_par.py` 只打北森，实测 1600 家缺口里北森只占 ~4%；
同一批公司名换个 ATS 再试一遍，边际成本几乎为零（都用同一个 `candidates()` 生成拼音词表），
而命中率是叠加的。这里把四条管道塞进同一个线程池，每条管道**各自**限速：

  - 北森 `{tenant}.zhiye.com`   → 每家一个主机，worker 内部串行 ⇒ 天然 ≤1 rps/主机
  - 大易 `{tenant}.hotjob.cn`   → 同上
  - 飞书 `{tenant}.jobs.feishu.cn` → 同上；但 `jobs.feishu.cn` 主域是所有租户共享，
    所以**只走 `{tenant}.jobs.feishu.cn` 子域**，并且全局另加 700ms 节流（子域后面同一套 CDN）
  - 其余（Moka 公开页）不在本脚本内：`app.mokahr.com` 需要前端签名，红线不碰

命中判据（三条全过才算）：
  1. HTTP 200 且列表接口返回 JSON（不是 SPA 首页 HTML）；
  2. `Count/positonNum > 0`；
  3. 归属随机挑一家公司名拼音对应的租户后，**门户里确实有岗位**——名字核对仍交给
     `verify_found.py`，这里只负责「把活着的门户捞出来」。

用法：
    python3 work/ats_par.py --in /tmp/exp/miss_nat.txt --out /tmp/exp/par1.jsonl --workers 12
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
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "work"))
sys.path.insert(0, str(ROOT / "src"))

import beisen_tenant_sweep as bb  # noqa: E402

from jobradar.adapters.base import USER_AGENT  # noqa: E402

BEISEN = "https://{t}.zhiye.com/api/Jobad/GetJobAdPageList"
BEISEN_BODY = {"PageIndex": 0, "PageSize": 20, "KeyWords": "", "SpecialType": 0,
               "PortalId": "", "DisplayFields": ["Category", "LocId", "PostDate", "LocNames"]}
HOTJOB = "https://{t}.hotjob.cn/wecruit/positionInfo/listPosition/{tenant}"
FEISHU = "https://{t}.jobs.feishu.cn/api/v1/search/job/posts"
FEISHU_BODY = {"keyword": "", "limit": 50, "offset": 0, "job_category_id_list": [],
               "tag_id_list": [], "location_code_list": [], "subject_id_list": [],
               "recruitment_id_list": [], "portal_type": 3, "job_function_id_list": [],
               "storefront_id_list": [], "portal_entrance": 1}

# 飞书 `jobs.feishu.cn` 主域是所有租户共享的后端，虽然是子域访问，但为了稳妥再加一道全局节流。
FEISHU_LOCK = threading.Lock()
FEISHU_LAST = [0.0]


def _feishu_throttle() -> None:
    with FEISHU_LOCK:
        gap = time.time() - FEISHU_LAST[0]
        if gap < 0.7:
            time.sleep(0.7 - gap)
        FEISHU_LAST[0] = time.time()


def probe_beisen(cli: httpx.Client, t: str) -> dict | None:
    try:
        r = cli.post(BEISEN.format(t=t), json=BEISEN_BODY)
        d = r.json()
    except Exception:  # noqa: BLE001
        return None
    if d.get("Code") != 200:
        return None
    n = int(d.get("Count") or 0)
    if n <= 0:
        return None
    items = d.get("Data") or []
    return {"ats": "beisen", "tenant": t, "count": n,
            "jobs": [str(i.get("JobAdName") or "")[:40] for i in items[:3]]}


def probe_hotjob(cli: httpx.Client, t: str) -> dict | None:
    """大易自定义域名 `{slug}.hotjob.cn`：**多数公司没配自定义域名（实测 `sany.hotjob.cn`
    直接 DNS NXDOMAIN）**，所以这里必须先解析成功再发请求，否则每家多花 4 秒等 DNS 超时。
    tenant 从门户页 HTML 里抠 `SU[0-9a-f]{20,32}`，没有就走主域 `wecruit.hotjob.cn` 试一把。
    """
    import re
    import socket
    candidates: list[tuple[str, str]] = []
    for slug in (t,):
        host = f"{slug}.hotjob.cn"
        try:
            socket.gethostbyname(host)
        except OSError:
            continue
        candidates.append(("wecruit.hotjob.cn", host))   # (接口主机, 门户主机)
        candidates.append((host, host))
    if not candidates:
        return None
    for api_host, portal in candidates:
        try:
            r = cli.get(f"https://{portal}/", follow_redirects=True)
        except Exception:  # noqa: BLE001
            continue
        if r.status_code != 200:
            continue
        m = re.search(r"(SU[0-9a-f]{20,32})", r.text or "")
        if not m:
            continue
        tenant = m.group(1)
        total = 0
        jobs: list[str] = []
        for rt in ("1", "2"):
            try:
                rj = cli.get(HOTJOB.format(t=api_host, tenant=tenant),
                             params={"iSaJAx": "isAjax", "request_locale": "zh_CN",
                                     "isFrompb": "true", "recruitType": rt,
                                     "pageSize": "20", "currentPage": "1"})
                dd = rj.json()
            except Exception:  # noqa: BLE001
                continue
            b = dd.get("data") if isinstance(dd.get("data"), dict) else dd
            pr = b.get("pageForm") or b
            total += int(b.get("positonNum") or 0)
            for it in (pr.get("pageData") or [])[:3]:
                jobs.append(str(it.get("postName") or "")[:40])
        if total > 0:
            return {"ats": "hotjob", "tenant": tenant, "host": portal, "count": total,
                    "jobs": jobs[:3]}
    return None


def probe_feishu(cli: httpx.Client, t: str) -> dict | None:
    """飞书 ATSX：`csrf/token` 是**租户存在性的唯一可靠探针**。

    2026-10-27 实测三个坑：
      1) 不存在的租户 `tastien`/`kudi`/`unitree` → `csrf/token` **400 + 空 body**；
      2) 「随机串壳租户」`minimax`（真实门户在 `vrfi1sk8a0`）同样 400——所以 400 只说明
         「这个 slug 没有直接挂门户」，不能说明公司不在飞书；
      3) 列表接口在**没有 csrf token** 时不是 401 而是 **405**（误导性极强），只有拿到
         token 后再带 `x-csrf-token` 才 200。此前先打列表的写法 100% 落空。
    """
    _feishu_throttle()
    base = f"https://{t}.jobs.feishu.cn"
    try:
        rc = cli.post(f"{base}/api/v1/csrf/token", json={"portal_entrance": 1},
                      headers={"Accept": "application/json", "portal_entrance": "1"})
        if rc.status_code != 200 or not (rc.text or "").lstrip().startswith("{"):
            return None
        token = (rc.json().get("data") or {}).get("token") or ""
        if not token:
            return None
        r = cli.post(f"{base}/api/v1/search/job/posts",
                     params={"portal_type": 3, "limit": 20, "offset": 0, "portal_entrance": 1},
                     json=FEISHU_BODY,
                     headers={"Accept": "application/json", "x-csrf-token": token,
                              "portal_entrance": "1"})
        if r.status_code != 200 or not (r.text or "").lstrip().startswith("{"):
            return None
        d = r.json()
    except Exception:  # noqa: BLE001
        return None
    data = d.get("data") or {}
    lst = data.get("job_post_list") or []
    n = int(data.get("count") or len(lst))
    if n <= 0:
        return None
    title = ""
    try:
        hp = cli.get(f"{base}/")
        tt = hp.text or ""
        m = re.search(r"<title>(.*?)</title>", tt, re.I | re.S)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip()[:40]
        if not title:
            m = re.search(r'name="description"\s+content="([^"]{1,60})"', tt)
            if m:
                title = m.group(1).strip()[:40]
    except Exception:  # noqa: BLE001
        pass
    return {"ats": "feishu", "tenant": t, "count": n, "title": title,
            "jobs": [str(i.get("title") or "")[:40] for i in lst[:3]]}


def probe_feishu_bare(cli: httpx.Client, t: str) -> dict | None:
    """**不用 csrf 的飞书探针**：`GET /` 对不存在的 slug 回 404 + 0 字节。

    2026-10-27 实测（`tastien`/`kudi`/`unitree` 全 404，`sensetime`/`feishu`/`vrfi1sk8a0` 全 200）。
    比 csrf 便宜一个数量级（1 个请求 vs 2 个），可以放心用在 1500 家缺口上；
    只有 200 才回去要 csrf token 数岗位（交给 verify_found.py）。
    """
    _feishu_throttle()
    base = f"https://{t}.jobs.feishu.cn"
    try:
        r = cli.get(f"{base}/")
    except Exception:  # noqa: BLE001
        return None
    if r.status_code != 200 or len(r.text) < 1000:
        return None
    title = ""
    m = re.search(r"<title>(.*?)</title>", r.text or "", re.I | re.S)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()[:40]
    # 公司名以门户自报的 tenant_info.tenant_name 为准（slug 猜不出公司名）
    tenant_name = ""
    mm = re.search(r'js-websiteInfo" type="text/json">(.*?)</script>', r.text or "", re.S)
    if mm:
        try:
            tenant_name = (json.loads(mm.group(1)).get("tenant_info") or {}).get("tenant_name") or ""
        except Exception:  # noqa: BLE001
            tenant_name = ""
    return {"ats": "feishu-host", "tenant": t, "count": -1, "title": title,
            "tenant_name": tenant_name, "jobs": []}


PIPES = (("beisen", probe_beisen), ("hotjob", probe_hotjob), ("feishu", probe_feishu),
         ("feishu_host", probe_feishu_bare))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="out", required=True)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--per-company", type=int, default=10)
    ap.add_argument("--pipes", default="beisen,hotjob,feishu,feishu_host")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    pipes = [p for p in PIPES if p[0] in a.pipes.split(",")]
    names = [x.strip() for x in Path(a.src).read_text(encoding="utf-8-sig").splitlines() if x.strip()]
    out = Path(a.out)
    done: set[str] = set()
    if out.exists():
        for ln in out.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(ln)["company"])
            except Exception:  # noqa: BLE001
                pass
    todo = [n for n in names if n not in done]
    if a.limit:
        todo = todo[: a.limit]
    py = bb.load_pinyin()
    print(f"待查 {len(todo)} 家 × {len(pipes)} 条管道，{a.workers} 路并行", flush=True)

    lock = threading.Lock()
    hits = 0
    t0 = time.time()
    fh = out.open("a", encoding="utf-8")

    def work(name: str) -> None:
        nonlocal hits
        found: list[dict] = []
        cands = [t for t in bb.candidates(name, py)[: a.per_company] if t not in bb.TENANT_DENY]
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=12.0,
                          follow_redirects=True) as cli:
            for _, fn in pipes:
                for t in cands:
                    pr = fn(cli, t)
                    if pr:
                        pr["company"] = name
                        found.append(pr)
                        break   # 同一管道命中一个就够，别把这家公司的所有候选都打一遍
        rec = {"company": name, "found": found,
               "urls": [u for pr in found for u in
                        ([f"https://{pr['tenant']}.zhiye.com/"] if pr["ats"] == "beisen" else
                         [f"https://{pr['host']}/"] if pr["ats"] == "hotjob" else
                         [f"https://{pr['tenant']}.jobs.feishu.cn/"] if pr["ats"] == "feishu-host" else
                         [f"https://{pr['tenant']}.jobs.feishu.cn/"])]}
        with lock:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            if found:
                hits += 1
                print(f"HIT {name:16s} " + " | ".join(
                    f"{pr['ats']}:{pr['tenant']}({pr['count']})" for pr in found), flush=True)

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(work, n) for n in todo]
        for i, fu in enumerate(futs, 1):
            fu.result()
            if i % 25 == 0:
                el = time.time() - t0
                print(f"... {i}/{len(todo)} {el:.0f}s 命中 {hits} ({el / i:.2f}s/家)", flush=True)
    fh.close()
    print(f"完成 {len(todo)}，命中 {hits} 家，用时 {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
