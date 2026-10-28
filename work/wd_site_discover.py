"""从 Workday 站点的 robots.txt 里拿 siteMap.xml 地址，反解出 site 段。

背景：Workday CXS 列表接口是 /wday/cxs/{tenant}/{site}/jobs，之前从 Common Crawl
只拿到 1,161 个主机名、没有 site 段，导致这批主机全部用不了。实测
`https://nvidia.wd5.myworkdayjobs.com/robots.txt` 第一行就是
`Sitemap: https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/siteMap.xml`，
site 段直接写在里面；3M 是 `/Search/siteMap.xml`。所以一个 robots.txt 请求就能补全。
"""
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

UA = "Mozilla/5.0 (compatible; jobradar/1.7; +https://github.com/lijiaqimun-coder/job_radar)"
SITEMAP = re.compile(r"^\s*Sitemap:\s*(\S+)", re.I | re.M)


def hosts() -> list[str]:
    out = []
    for line in Path("work/cc_hosts.tsv").read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0] == "workday":
            out.append(parts[1])
    return sorted(set(out))


def discover(host: str, client: httpx.Client) -> dict:
    rec = {"host": host, "tenant": host.split(".")[0], "site": None, "sitemap": None}
    try:
        r = client.get(f"https://{host}/robots.txt")
        m = SITEMAP.search(r.text)
        if m:
            sm = m.group(1)
            rec["sitemap"] = sm
            path = httpx.URL(sm).path  # /NVIDIAExternalCareerSite/siteMap.xml
            seg = [p for p in path.split("/") if p]
            if len(seg) >= 2 and seg[-1].lower() == "sitemap.xml":
                rec["site"] = seg[-2]
        rec["status"] = r.status_code
    except Exception as e:  # 网络抖动不该中断整批
        rec["err"] = type(e).__name__
    return rec


def main() -> None:
    hs = hosts()
    done = set()
    out = Path("work/wd_sites.jsonl")
    if out.exists():
        done = {json.loads(line)["host"] for line in out.read_text(encoding="utf-8").splitlines() if line.strip()}
    todo = [h for h in hs if h not in done]
    print(f"hosts={len(hs)} todo={len(todo)}", flush=True)
    with httpx.Client(timeout=15, follow_redirects=True, headers={"User-Agent": UA}) as client, \
            out.open("a", encoding="utf-8") as fh, ThreadPoolExecutor(max_workers=12) as ex:
        for i, rec in enumerate(ex.map(lambda h: discover(h, client), todo), 1):
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            if i % 100 == 0:
                print(f"{i}/{len(todo)}", flush=True)
    ok = sum(1 for line in out.read_text(encoding="utf-8").splitlines() if json.loads(line).get("site"))
    print(f"done; with site={ok}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
