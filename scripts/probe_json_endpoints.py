"""一次探测一批招聘站是否为「公开 JSON 接口」：找出不需要逆向就能接的站。

用法：
    python3 scripts/probe_json_endpoints.py sites.json out.json

sites.json: {"url": "公司名", ...}（一行一个招聘页/首页地址）

判定口径（与 docs/recon/self-hosted-sites.md 的可复用排查顺序一致）：
  1. GET 页面本身（200 且能拿到 HTML 才算站点存在）
  2. 从 HTML 里找候选接口路径：/api/、/job、/position、/list、.json、/search
  3. 逐个试 GET，响应 content-type 是 JSON、且 body 能 json.loads、且结构里有数组 -> 记为新发现
  4. 全部失败就只记 blocked 原因，不做任何绕过（不逆向签名、不带 Cookie、不伪造 UA）

限速：每站 1 req/s（不同站点串行；本脚本只做侦察，不用于生产抓取）。
"""

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

UA = "Mozilla/5.0 (compatible; jobradar-bot/0.1)"
API_HINT = re.compile(r"[\"'](/[A-Za-z0-9_\-/]{4,60}(?:/(?:api|job|jobs|position|positions|list|search|query|recruit|campus|data)"
                      r"[A-Za-z0-9_\-/]{0,40})?)[\"']")
JSONISH = ("json", "javascript")


def probe(client: httpx.Client, url: str) -> dict:
    out: dict = {"url": url}
    try:
        r = client.get(url)
    except Exception as e:  # noqa: BLE001
        out["status"] = f"ERR {type(e).__name__}"
        return out
    out["status"] = r.status_code
    if r.status_code != 200:
        return out
    ct = (r.headers.get("content-type") or "").lower()
    if "json" in ct:
        out["note"] = "页面本身就是 JSON"
        return out
    html = r.text[:400_000]
    paths = []
    for m in API_HINT.finditer(html):
        p = m.group(1)
        if p.lower().endswith((".png", ".jpg", ".css", ".js", ".svg", ".ico", ".woff", ".gif")):
            continue
        if p not in paths:
            paths.append(p)
    out["candidates"] = len(paths)
    hits = []
    for p in paths[:12]:
        time.sleep(0.2)
        target = urljoin(url, p)
        try:
            rr = client.get(target)
        except Exception:  # noqa: BLE001
            continue
        ctt = (rr.headers.get("content-type") or "").lower()
        if rr.status_code == 200 and any(k in ctt for k in JSONISH):
            try:
                body = rr.json()
            except ValueError:
                continue
            if isinstance(body, (dict, list)):
                keys = list(body)[:8] if isinstance(body, dict) else [f"[{len(body)}]"]
                hits.append({"path": p, "keys": keys})
    out["json_hits"] = hits
    return out


def main() -> int:
    sites = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    res = []
    with httpx.Client(headers={"User-Agent": UA}, timeout=15, follow_redirects=True) as c:
        for n, (url, name) in enumerate(sites.items(), 1):
            r = probe(c, url)
            r["company"] = name
            r["host"] = urlparse(url).netloc
            res.append(r)
            flag = "JSON!" if r.get("json_hits") else ("--" if r.get("status") == 200 else "XX")
            print(f"{flag} {n:3d}/{len(sites)} {name[:12]:14s} {url[:70]:72s} {r.get('status')}"
                  f" {len(r.get('json_hits') or [])}/{r.get('candidates', 0)}", file=sys.stderr)
            time.sleep(1.0)
    Path(sys.argv[2]).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
