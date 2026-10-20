"""侦察探针：按清单逐条发请求（间隔 ≥1s），每个站点先读 robots.txt，打印状态码/类型/大小/耗时与响应开头。
用于侦察接口形态，以及验证"从 GitHub Actions 能否访问目标站点"。只读、低频。

用法：
  python scripts/recon_probe.py URL [URL ...]
  python scripts/recon_probe.py --file docs/recon/probe.txt [--body 4000]

清单文件每行一条：`GET <url>` 或 `POST <url> <json body>`；# 开头为注释。
"""

import argparse
import json
import sys
import time
from urllib.parse import urlsplit

import httpx

UA = "jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; recon probe)"


def parse_lines(lines: list[str]) -> list[tuple[str, str, dict | None]]:
    out = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(" ", 2)
        if parts[0] in ("GET", "POST"):
            body = json.loads(parts[2]) if len(parts) > 2 else None
            out.append((parts[0], parts[1], body))
        else:
            out.append(("GET", parts[0], None))
    return out


def probe(client, method, url, body, body_chars):
    t = time.monotonic()
    try:
        r = client.request(method, url, json=body)
    except httpx.HTTPError as e:
        print(f"ERROR {type(e).__name__}: {e} | {time.monotonic() - t:.1f}s | {method} {url}")
        return
    print(f"{r.status_code} | {r.headers.get('content-type', '-')} | {len(r.content)}B | "
          f"{time.monotonic() - t:.1f}s | {method} {url} -> {r.url}")
    if body_chars:
        print("----- body -----")
        print(r.text[:body_chars])
        print("----- end -----")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="*")
    ap.add_argument("--file")
    ap.add_argument("--body", type=int, default=0, help="打印响应正文的前 N 个字符")
    args = ap.parse_args()
    lines = list(args.urls)
    if args.file:
        lines += open(args.file, encoding="utf-8").read().splitlines()

    headers = {"User-Agent": UA, "Accept": "application/json, text/html;q=0.9"}
    with httpx.Client(headers=headers, timeout=20, follow_redirects=True) as client:
        seen_hosts = set()
        for method, url, body in parse_lines(lines):
            parts = urlsplit(url)
            host = f"{parts.scheme}://{parts.netloc}"
            if host not in seen_hosts:
                seen_hosts.add(host)
                print(f"\n===== {host} =====")
                probe(client, "GET", f"{host}/robots.txt", None, 2000)
                time.sleep(1)
            probe(client, method, url, body, args.body)
            time.sleep(1.5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
