"""侦察探针：按清单逐条发请求（间隔 ≥1.5s），每个站点先读 robots.txt。只读、低频。
用于侦察接口形态，以及验证"从 GitHub Actions 能否访问目标站点"。

用法：
  python scripts/recon_probe.py --file docs/recon/probe.txt [--body 3000]

清单每行一条（# 开头为注释）：
  GET  <url>                  HTML 只打印标题/脚本地址/疑似接口路径/内嵌 JSON 片段；JSON 打印正文开头
  POST <url> <json body>
  GREP <url> <正则>           打印正则的去重匹配（用于在 JS 包里找接口）
"""

import argparse
import json
import re
import sys
import time
from urllib.parse import urlsplit

import httpx

UA = "jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; recon probe)"
API_LIKE = re.compile(r"""["'`]((?:https?:)?/{1,2}[\w.\-]*/?[\w\-/.]*(?:api|portal|recruit|job|position|campus)[\w\-/.]*)["'`]""", re.I)
SCRIPT_SRC = re.compile(r"""<script[^>]+src=["']([^"']+)["']""", re.I)
INLINE_JSON = re.compile(r"""(window\.__[\w]+__\s*=|<script[^>]+type=["'](?:application|text)/json["'][^>]*>)""", re.I)


def parse_lines(lines):
    out = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(" ", 2)
        out.append((parts[0], parts[1], parts[2] if len(parts) > 2 else None))
    return out


def uniq(items, n=40):
    seen, out = set(), []
    for i in items:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out[:n]


def report(r: httpx.Response, body_chars: int, regex: str | None):
    ctype = r.headers.get("content-type", "")
    text = r.text
    if regex:
        for m in uniq(re.findall(regex, text), 60):
            print("  MATCH", (m if isinstance(m, str) else " | ".join(m))[:300])
        return
    if "json" in ctype or text.lstrip()[:1] in "{[":
        print("  JSON", text[:body_chars])
        return
    t = re.search(r"<title>(.*?)</title>", text, re.S | re.I)
    print("  TITLE", t.group(1).strip()[:100] if t else "-")
    for s in uniq(SCRIPT_SRC.findall(text), 25):
        print("  SCRIPT", s[:250])
    for a in uniq(API_LIKE.findall(text), 40):
        print("  PATH", a[:250])
    for m in list(INLINE_JSON.finditer(text))[:5]:
        print("  INLINE", text[m.start():m.start() + min(body_chars, 1500)].replace("\n", " "))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--body", type=int, default=3000)
    args = ap.parse_args()
    reqs = parse_lines(open(args.file, encoding="utf-8").read().splitlines())

    headers = {"User-Agent": UA, "Accept": "application/json, text/html;q=0.9, */*;q=0.5"}
    with httpx.Client(headers=headers, timeout=20, follow_redirects=True) as client:
        seen_hosts = set()
        for verb, url, extra in reqs:
            host = "{0.scheme}://{0.netloc}".format(urlsplit(url))
            if host not in seen_hosts:
                seen_hosts.add(host)
                print(f"\n===== {host} =====")
                try:
                    rb = client.get(f"{host}/robots.txt")
                    body = rb.text[:800] if "html" not in rb.headers.get("content-type", "") else "(html, no robots)"
                    print(f"ROBOTS {rb.status_code}: {body}")
                except httpx.HTTPError as e:
                    print(f"ROBOTS ERROR {type(e).__name__}")
                time.sleep(1.5)
            t = time.monotonic()
            try:
                if verb == "POST":
                    r = client.post(url, json=json.loads(extra or "{}"))
                else:
                    r = client.get(url)
            except httpx.HTTPError as e:
                print(f"\n>>> {verb} {url}\nERROR {type(e).__name__}: {e}")
                time.sleep(1.5)
                continue
            print(f"\n>>> {verb} {url}\n{r.status_code} | {r.headers.get('content-type', '-')} | "
                  f"{len(r.content)}B | {time.monotonic() - t:.1f}s | final={r.url}")
            report(r, args.body, extra if verb == "GREP" else None)
            time.sleep(1.5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
