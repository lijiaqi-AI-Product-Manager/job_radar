"""侦察探针：对给定 URL 各发 1 次 GET，并读取其站点的 robots.txt，打印状态码/类型/大小/耗时。
用于验证"从 GitHub Actions 能否访问目标站点"。只读、低频（请求间隔 ≥1s）。

用法：python scripts/recon_probe.py URL [URL ...]
"""

import sys
import time
from urllib.parse import urlsplit

import httpx

UA = "jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; recon probe)"


def probe(client: httpx.Client, url: str) -> str:
    t = time.monotonic()
    try:
        r = client.get(url)
        return (f"{r.status_code} | {r.headers.get('content-type', '-')} | {len(r.content)}B | "
                f"{time.monotonic() - t:.1f}s | {url}")
    except httpx.HTTPError as e:
        return f"ERROR {type(e).__name__} | {time.monotonic() - t:.1f}s | {url}"


def main(urls: list[str]) -> int:
    with httpx.Client(headers={"User-Agent": UA}, timeout=20, follow_redirects=True) as client:
        seen_hosts = set()
        for url in urls:
            parts = urlsplit(url)
            host = f"{parts.scheme}://{parts.netloc}"
            if host not in seen_hosts:
                seen_hosts.add(host)
                print("ROBOTS", probe(client, f"{host}/robots.txt"))
                time.sleep(1)
            print("PAGE  ", probe(client, url))
            time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
