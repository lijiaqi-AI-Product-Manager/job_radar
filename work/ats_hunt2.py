"""ATS 指纹识别 v2：curl 直连 Bing 搜索 + 正则抽链接 + 指纹匹配 + 子域探测。

比 v1（Playwright 开页面）快 10-20 倍：搜索结果用 HTTP 直取，不渲染 JS。
并发 8 线程，每个线程自己的 session，Bing 侧限速 1 请求/秒/线程。

用法：python3 work/ats_hunt2.py [start] [limit]
输出：work/ats_findings.jsonl（可续跑，已存在的公司自动跳过）
"""

import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

ATS_PATTERNS = [
    (r"\.zhiye\.com", "beisen"),
    (r"\.myworkdayjobs\.com", "workday"),
    (r"myworkdaysite\.com", "workday"),
    (r"hotjob\.cn", "hotjob"),
    (r"dayee\.com", "hotjob"),
    (r"mokahr\.com", "moka"),
    (r"\.jobs\.feishu\.cn|jobs\.bytedance\.com", "feishu_atsx"),
    (r"italent\.cn", "beisen_legacy"),
    (r"smartrecruiters\.com", "smartrecruiters"),
    (r"successfactors\.(com|eu)", "successfactors"),
    (r"icims\.com", "icims"),
    (r"taleo\.net", "taleo"),
    (r"avature\.net", "avature"),
    (r"workable\.com", "workable"),
    (r"greenhouse\.io", "greenhouse"),
    (r"lever\.co", "lever"),
    (r"bamboohr\.com", "bamboohr"),
]

BLOCK = re.compile(r"51job|zhaopin\.com|liepin|zhipin\.com|yingjiesheng|nowcoder|maimai|kanzhun|"
                   r"shixiseng|baidu\.com|so\.com|sogou|zhihu|douban|weibo|xiaohongshu|bilibili|"
                   r"qcc\.com|tianyancha|aiqicha|qixin|lagou|linkedin|glassdoor|wikipedia|"
                   r"baike|csdn|cnblogs|jianshu|sohu|gaokao|dxsbb|offcn|huatu|chinahr|jobui|"
                   r"zhaopin|jobui|dajie|58\.com|ganji|jiuye|job\.moe|bing\.com|microsoft")

SUBS = ("careers", "job", "hr")


def ats_of(s: str) -> str | None:
    s = s.lower()
    for pat, name in ATS_PATTERNS:
        if re.search(pat, s):
            return name
    return None


def host_of(u: str) -> str:
    try:
        return (urlparse(u).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return ""


_local = threading.local()


def client() -> httpx.Client:
    if not hasattr(_local, "c"):
        _local.c = httpx.Client(
            headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"},
            timeout=12, follow_redirects=True, verify=False,
        )
    return _local.c


def search_links(company: str) -> list[str]:
    """Bing 搜索，返回结果里的外链 URL 列表（去重保序）。"""
    q = quote(f"{company} 招聘 官网")
    out: list[str] = []
    for _attempt in range(2):
        try:
            r = client().get(f"https://cn.bing.com/search?q={q}&count=20")
            if r.status_code != 200:
                time.sleep(2)
                continue
            for m in re.finditer(r'href="(https?://[^"]+)"', r.text):
                u = m.group(1)
                if "bing.com" in u or "microsoft" in u:
                    continue
                u = u.split("&amp;")[0]
                if u not in out:
                    out.append(u)
            if out:
                return out
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return out


def probe_sub(domain: str) -> dict:
    for sub in SUBS:
        u = f"https://{sub}.{domain}/"
        try:
            r = client().get(u)
            if r.status_code == 200 and len(r.text) > 500:
                final = str(r.url)
                a = ats_of(final) or ats_of(r.text[:40000])
                return {"careers_url": final, "ats": a or "self_built"}
        except Exception:  # noqa: BLE001
            continue
    return {}


def work_one(row: dict) -> dict:
    name = row["name"]
    res = {"company": name, "sector": row["sector"], "ats": None, "careers_url": None, "hosts": []}
    links = search_links(name)
    time.sleep(0.9)
    res["n_results"] = len(links)
    hosts: list[str] = []
    for u in links:
        h = host_of(u)
        if not h or BLOCK.search(h):
            continue
        if h not in hosts:
            hosts.append(h)
        a = ats_of(u)
        if a:
            res.update(ats=a, careers_url=u)
            break
    if not res["ats"]:
        # 用首 1 个疑似官网域名试子域（控制耗时）
        for h in hosts[:1]:
            parts = h.split(".")
            if len(parts) < 2:
                continue
            root = ".".join(parts[-2:]) if not (len(parts) >= 3 and parts[-2] in ("com", "net", "org", "gov", "edu")) else ".".join(parts[-3:])
            pr = probe_sub(root)
            if pr:
                res.update(pr)
                break
    res["hosts"] = hosts[:5]
    return res


def main():
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 2000

    rows = []
    for ln in (WORK / "candidates_clean.tsv").read_text(encoding="utf-8").splitlines():
        p = ln.split("\t")
        if len(p) >= 3:
            rows.append({"name": p[0], "sector": p[1]})

    done = set()
    for f in (WORK / "ats_findings.jsonl", WORK / "ats_findings_part0.jsonl"):
        if f.exists():
            for ln in f.read_text(encoding="utf-8").splitlines():
                try:
                    done.add(json.loads(ln)["company"])
                except Exception:  # noqa: BLE001
                    pass
    # 北森已命中的也跳过
    pb = WORK / "probe_all.jsonl"
    if pb.exists():
        for ln in pb.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(ln)
                if r.get("matched"):
                    done.add(r["company"])
            except Exception:  # noqa: BLE001
                pass

    todo = [r for r in rows if r["name"] not in done][start: start + limit]
    print(f"待处理 {len(todo)} 家（已完成 {len(done)}）", flush=True)

    lock = threading.Lock()
    out = open(WORK / "ats_findings.jsonl", "a", encoding="utf-8")
    cnt = [0]

    def run(row):
        try:
            r = work_one(row)
        except Exception as e:  # noqa: BLE001
            r = {"company": row["name"], "sector": row["sector"], "ats": None, "error": type(e).__name__}
        with lock:
            out.write(json.dumps(r, ensure_ascii=False) + "\n")
            out.flush()
            cnt[0] += 1
            if cnt[0] % 25 == 0:
                print(f"{cnt[0]}/{len(todo)}", flush=True)

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(run, todo))
    out.close()
    print("done")


if __name__ == "__main__":
    main()
