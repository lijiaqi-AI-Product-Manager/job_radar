"""找同款就业网 CMS：用搜索引擎查 `correcruit` 路径特征，抽出用了同款 CMS 的高校域名。

南开用的路径是 /correcruit/index/p/N.html 与 /correcruit/content/id/N.html。
若能找到其它学校也用 correcruit，就能把 campus 适配器一行注册一个新 school 铺开。

输出 work/_campus_cms.txt（UTF-8）
"""
from __future__ import annotations

import re
import time
import urllib.parse
from collections import Counter
from pathlib import Path

import httpx

OUT = Path("work/_campus_cms.txt")
H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}
QUERIES = [
    "correcruit/index/p",
    "correcruit/content/id",
    "inurl:correcruit 招聘",
]
DOMAIN = re.compile(r"https?://([a-z0-9][a-z0-9.-]*\.(?:edu\.cn|com))", re.I)


def so360(client: httpx.Client, q: str, page: int) -> str:
    r = client.get("https://www.so.com/s", params={"q": q, "pn": page})
    return urllib.parse.unquote(r.text)


def sogou(client: httpx.Client, q: str, page: int) -> str:
    r = client.get("https://www.sogou.com/web", params={"query": q, "ie": "utf8", "page": page})
    return urllib.parse.unquote(r.text)


def main() -> None:
    lines = []
    hits: Counter[str] = Counter()
    with httpx.Client(timeout=15.0, headers=H, follow_redirects=True, verify=False) as c:
        for q in QUERIES:
            for engine, fn in (("so360", so360), ("sogou", sogou)):
                for page in (1, 2):
                    try:
                        b = fn(c, q, page)
                    except Exception as exc:  # noqa: BLE001
                        lines.append(f"[{engine}] {q} p{page} ERROR {type(exc).__name__}: {exc}")
                        time.sleep(3)
                        continue
                    doms = Counter(DOMAIN.findall(b))
                    has = "correcruit" in b
                    lines.append(
                        f"[{engine}] {q} p{page} bytes={len(b)} correcruit={has} "
                        f"domains={len(doms)} top={doms.most_common(6)}"
                    )
                    for d, n in doms.items():
                        hits[d] += n
                    time.sleep(3.0)
    lines.append("")
    lines.append("== merged domains ==")
    for d, n in hits.most_common(60):
        lines.append(f"{n}\t{d}")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote", OUT, len(hits))


if __name__ == "__main__":
    main()
