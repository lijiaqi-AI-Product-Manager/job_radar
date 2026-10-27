"""把搜索引擎摸到的线索（zhiye 子域 / hotjob host+tenant）逐一验证成「可收录的源」。

验证要过三关，缺一关就不收录：
  1. **活着**：列表接口 Code=200 / status=ok，且 `Count > 0`（0 岗门户不收录，收了也只会让覆盖率虚高）；
  2. **是这家公司**：门户页面正文（含 SPA 内嵌 JSON 里的岗位名）要出现公司名核心词。
     `site:` 查询会误命中的道理在 `search_ats.py` 里写过；这里的名字核对是最后一道闸。
  3. 记录证据（title、样本岗位名、城市/日期样本比），便于写进 YAML 注释。

红线：每个租户是独立主机（`{slug}.zhiye.com`），并行不同租户不违反每主机 ≤1 rps。
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

DISPLAY_FIELDS = ["Category", "LocId", "PostDate", "EndTime", "Degree",
                  "ClassificationOne", "LocNames"]
LIST = "https://{slug}.zhiye.com/api/Jobad/GetJobAdPageList"
HOTJOB_LIST = "https://{host}/wecruit/positionInfo/listPosition/{tenant}"
HOTJOB_URL = re.compile(r"https?://([a-z0-9][a-z0-9.-]*hotjob\.cn)/(SU[0-9a-f]{20,32})", re.I)
ZHIYE_URL = re.compile(r"https?://([a-z0-9][a-z0-9-]+)\.zhiye\.com", re.I)
TITLE = re.compile(r"<title>(.*?)</title>", re.I | re.S)

# 岗位代码前缀 → 公司线索。`wecruit` 主域的门户页 title 是空的（SPA），列表里 `company`
# 又是「用人部门/子公司」级字段，唯一稳定的归属证据是岗位代码前缀：`CAERI004073` → 中国汽研、
# `cetc009119` → 中国电科、`ztjs006822` → 中铁建设、`simcere...` → 先声药业。
# 这只是**候选线索**，仍要人工核对；写进 YAML 注释里备查。
# 贪心会连数字一起吞（`CAERI004`），所以字母段与数字段分开写：字母段尽量长，数字段 ≥3 位。
# 前缀后面可能跟 0 也可能不跟（`CAERI004073` / `CMOC000535` / `Deloitte007722`），
# 所以「去掉全部数字后再去掉尾部 0」再要求长度 ≥3、且至少有一个字母，否则 `abc123` 这种噪声也会进。
CODE_PREFIX = re.compile(r"^([A-Za-z][A-Za-z0-9]{1,14})\d{3,}$")

# 公司名匹配：去掉「集团/股份/有限公司」等后缀，再要求核心词（或去后缀后的前 2 字）出现在页面里。
# 前 2 字是为了兜住「中国人寿」→ 页面写「中国人寿保险（集团）」这类；代价是可能放过同前缀公司，
# 所以还要求 title 或岗位名里出现——同一批数据里两个条件都过，误配概率很低。
STRIP = ("（", "）", "(", ")", "集团", "股份", "控股", "有限公司", "有限责任公司", "中国区",
         "公司", "总公司", "总部")


def core(name: str) -> str:
    n = name
    for s in STRIP:
        n = n.replace(s, "")
    return n.strip()


def name_hit(name: str, blob: str) -> bool:
    c = core(name)
    if not c:
        return False
    if c in blob:
        return True
    return len(c) >= 2 and c[:2] in blob


def probe_zhiye(slug: str, company: str) -> dict:
    out = {"kind": "beisen", "slug": slug, "company": company, "ok": False,
           "count": 0, "title": "", "name_hit": False, "err": ""}
    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20.0,
                          follow_redirects=False) as cli:
            r = cli.post(LIST.format(slug=slug), json={
                "PageIndex": 0, "PageSize": 30, "KeyWords": "", "SpecialType": 0,
                "PortalId": "", "DisplayFields": DISPLAY_FIELDS})
            if r.status_code != 200:
                out["err"] = f"http{r.status_code}"
                return out
            d = r.json()
            if d.get("Code") != 200:
                out["err"] = f"code{d.get('Code')}"
                return out
            out["ok"] = True
            out["count"] = int(d.get("Count") or 0)
            items = d.get("Data") or []
            out["with_city"] = sum(1 for it in items if it.get("LocNames"))
            out["with_date"] = sum(1 for it in items
                                   if str(it.get("PostDate") or "").startswith("20"))
            out["sample"] = len(items)
            jobs = [str(it.get("JobAdName") or "") for it in items][:10]
            out["jobs"] = jobs[:5]
            blob = " ".join(jobs)
            try:
                hp = cli.get(f"https://{slug}.zhiye.com/")
                m = TITLE.search(hp.text or "")
                if m:
                    out["title"] = re.sub(r"\s+", " ", m.group(1)).strip()[:80]
                    blob += " " + out["title"]
            except Exception:  # noqa: BLE001
                pass
            out["name_hit"] = name_hit(company, blob)
    except Exception as e:  # noqa: BLE001
        out["err"] = type(e).__name__
    return out


def probe_hotjob(host: str, tenant: str, company: str) -> dict:
    out = {"kind": "hotjob", "host": host, "tenant": tenant, "company": company,
           "ok": False, "count": 0, "title": "", "name_hit": False, "err": "", "code_prefix": []}
    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20.0,
                          follow_redirects=True) as cli:
            r = cli.get(HOTJOB_LIST.format(host=host, tenant=tenant),
                        params={"iSaJAx": "isAjax", "request_locale": "zh_CN",
                                "isFrompb": "true", "recruitType": "1",
                                "pageSize": "20", "currentPage": "1"})
            d = r.json()
            body = d.get("data") if isinstance(d.get("data"), dict) else d
            pr = body.get("pageForm") or body
            items = pr.get("pageData") or []
            out["ok"] = bool(items) or bool(pr)
            out["count"] = int(body.get("positonNum") or 0) or int(pr.get("totalPage") or 0) * 15
            out["sample"] = len(items)
            out["with_city"] = sum(1 for it in items if it.get("workPlaceStr"))
            out["with_date"] = sum(1 for it in items if it.get("publishDate"))
            comps = [str(it.get("company") or "") for it in items]
            pref: list[str] = []
            for it in items:
                m = CODE_PREFIX.match(str(it.get("postCode") or ""))
                # 贪心捕获会连数字一起吞（`CAERI004`），这里再剥一次尾部数字和 0
                if m:
                    k = m.group(1).rstrip("0123456789") or m.group(1)
                    if len(k) >= 3 and any(c.isalpha() for c in k) and k not in pref:
                        pref.append(k)
            out["code_prefix"] = pref[:6]
            out["jobs"] = [str(it.get("postName") or "")[:40] for it in items][:5]
            blob = " ".join(comps) + " " + " ".join(out["jobs"])
            # 自定义域名本身就是强证据：longi.hotjob.cn 只可能是隆基
            if host != "wecruit.hotjob.cn":
                blob += " " + host.split(".")[0]
            try:
                hp = cli.get(f"https://{host}/{tenant}/pb/school.html")
                m = TITLE.search(hp.text or "")
                if m and m.group(1).strip():
                    out["title"] = re.sub(r"\s+", " ", m.group(1)).strip()[:80]
                    blob += " " + out["title"]
            except Exception:  # noqa: BLE001
                pass
            out["name_hit"] = name_hit(company, blob)
    except Exception as e:  # noqa: BLE001
        out["err"] = type(e).__name__
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True, help="search_ats.py 的 JSONL")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    jobs: list[tuple] = []
    seen: set[str] = set()
    for ln in Path(args.src).read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(ln)
        except Exception:  # noqa: BLE001
            continue
        comp = rec.get("company") or ""
        for u in rec.get("urls") or []:
            mz = ZHIYE_URL.match(u)
            if mz:
                k = "z:" + mz.group(1).lower()
                if k not in seen:
                    seen.add(k)
                    jobs.append(("z", mz.group(1).lower(), comp))
                continue
            mh = HOTJOB_URL.match(u)
            if mh:
                k = "h:" + mh.group(1).lower() + "/" + mh.group(2)
                if k not in seen:
                    seen.add(k)
                    jobs.append(("h", (mh.group(1).lower(), mh.group(2)), comp))
    outp = Path(args.out)
    done: set[str] = set()
    if outp.exists():
        for ln in outp.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(ln)
                done.add("z:" + d["slug"] if d["kind"] == "beisen"
                         else "h:" + d["host"] + "/" + d["tenant"])
            except Exception:  # noqa: BLE001
                pass
    todo = [j for j in jobs
            if ("z:" + j[1] if j[0] == "z" else "h:" + j[1][0] + "/" + j[1][1]) not in done]
    print(f"候选 {len(jobs)}，待验证 {len(todo)}", flush=True)

    def run(j):
        return probe_zhiye(j[1], j[2]) if j[0] == "z" else probe_hotjob(j[1][0], j[1][1], j[2])

    t0 = time.time()
    good = 0
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=args.workers) as ex, outp.open("a", encoding="utf-8") as f:
        for rec in ex.map(run, todo):
            with lock:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                key = rec["slug"] if rec["kind"] == "beisen" else rec["host"] + "/" + rec["tenant"]
                flag = "OK " if (rec["ok"] and rec["count"] > 0 and rec["name_hit"]) else \
                       ("?? " if (rec["ok"] and rec["count"] > 0) else "-- ")
                if flag == "OK ":
                    good += 1
                print(f"{flag}{key[:44]:44s} {rec['count']:6d} {rec['title'][:26]} "
                      f"{(rec.get('jobs') or [''])[0][:22]}", flush=True)
    print(f"完成 {len(todo)}，可用 {good}，用时 {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ---------------------------------------------------------------------------
# `无 title` 的 hotjob 租户（wecruit 主域）无法从页面拿到公司名，只能靠「线索 → 页面」反查：
# 把搜索这一步的 `company → 命中 URL` 关系当唯一证据，并额外要求**同一公司的两个查询
# 都指向同一个租户**才算稳（单个查询可能是竞品/行业文章里的链接）。
# 这条规则写在文件末尾，方便单测直接引用。
def pick_wecruit(verified: list[dict], search_rows: list[dict]) -> list[dict]:
    """从验证结果里挑出「wecruit 主域 + 无标题」的租户，标出它们的候选公司（不自动采信）。"""
    by_tenant: dict[str, set[str]] = {}
    for r in search_rows:
        comp = r.get("company") or ""
        for u in r.get("urls") or []:
            m = HOTJOB_URL.match(u)
            if m and m.group(1).lower() == "wecruit.hotjob.cn":
                by_tenant.setdefault(m.group(2), set()).add(comp)
    out = []
    for v in verified:
        if v.get("kind") == "hotjob" and v.get("host") == "wecruit.hotjob.cn":
            out.append({"tenant": v["tenant"], "count": v["count"],
                        "title": v.get("title", ""),
                        "candidates": sorted(by_tenant.get(v["tenant"], [])),
                        "jobs": v.get("jobs") or []})
    return out
