"""探测 51job / 智联 的公开搜索接口（无登录）是否可用；只读、只取 1 页。"""

import json
import urllib.parse
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
H = {"User-Agent": UA, "Referer": "https://we.51job.com/pc/search", "Accept": "application/json"}

job51 = "https://we.51job.com/api/job/search-pc?" + urllib.parse.urlencode({
    "api_key": "51job", "timestamp": "1", "keyword": "工商银行", "searchType": "2",
    "jobArea": "000000", "sortType": "0", "pageNum": "1", "requestId": "", "pageSize": "20",
    "source": "1", "accountId": "", "pageCode": "sou|sou|soulb",
})

zp = "https://fe-api.zhaopin.com/c/i/search/positions?" + urllib.parse.urlencode({
    "start": "0", "pageSize": "20", "cityId": "489", "kw": "工商银行", "kt": "3",
})


def main() -> None:
    out = {}
    with httpx.Client(timeout=25, follow_redirects=True, headers=H) as c:
        for name, url in (("51job", job51), ("zhaopin", zp)):
            try:
                r = c.get(url)
                body = r.text
                out[name] = {"status": r.status_code, "len": len(body), "head": body[:300]}
            except Exception as e:  # noqa: BLE001
                out[name] = {"error": f"{type(e).__name__}: {e}"}
    (ROOT / "work" / "_chan4.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("ok")


if __name__ == "__main__":
    main()
