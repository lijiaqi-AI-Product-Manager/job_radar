"""用招聘门户的 `<title>` 反查公司名：判断「这家到底有没有可抓的门户」。

为什么需要：1560 家缺口公司里，大部分不是「爬不到」，而是**根本没有公开校招门户**
（用第三方招聘网站、或只发在公众号）。要证明这一点，不能靠"我搜不到"，
得拿一个**可复现的判据**：搜索引擎是否索引到过带这家公司名的门户标题。

做法：对候选名做一次 `{name} 招聘官网` 的搜索，从结果片段里找
「XX招聘官网 / XX人才招聘 / XX校园招聘」这类标题模式，抽出公司名与命中的域名。
命中的进「待验证入口」，没命中的进「疑似无公开门户」，两条都留证据。

红线：只读搜索结果页，同主机 ≤1 rps，每公司 1 条查询。
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import USER_AGENT  # noqa: E402

HREF = re.compile(r'href="(https?://[^"]+)"', re.I)
# 这些站点的页面标题里全是「XX 招聘官网」式的片段，但跟公司门户毫无关系：
# 百科/字典/诗词站（`hanyuguoxue`、`zdic`、`chagushici` 是必应为「招聘」二字配的字典结果）、
# 企业信息站（爱企查/企查查/天眼查）、新闻与问答。不过滤的话 `has_portal` 里会有
# 一大半是百科词条，后面探测全打在百度百科上（实测 1794 次 baike 命中）。
JUNK = ("bing.com", "microsoft", "msn.com", "go.microsoft",
        "baike.baidu.com", "aiqicha", "qcc.com", "tianyancha", "qixin.com",
        "zhihu.com", "hanyuguoxue", "hgcha.com", "zdic.net", "chagushici", "gushici.net",
        "shidianguji", "zgbk.com", "dict.revised.moe", "hanyu.baidu",
        "zhipin.com", "zhaopin.com", "liepin.com", "51job.com", "yingjiesheng.com",
        "nowcoder.com", "maimai.cn", "kanzhun.com", "shixiseng.com", "lagou.com",
        "sohu.com", "thepaper.cn", "people.com.cn", "china.com.cn", "163.com",
        "eastmoney.com", "chsi.com.cn", "gov.cn", "wikipedia", "baidu.com",
        "douban", "weibo", "csdn", "jianshu", "xiaohongshu", "bilibili")
TITLE_PAT = re.compile(r"([\u4e00-\u9fa5A-Za-z0-9·（）()]{2,24})(招聘官网|人才招聘|招聘门户|校园招聘|社会招聘)")


def main() -> int:
    src = Path(sys.argv[1])
    out = Path(sys.argv[2])
    names = [ln.strip() for ln in src.read_text(encoding="utf-8-sig").splitlines() if ln.strip()]
    done: set[str] = set()
    if out.exists():
        for ln in out.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(ln)["company"])
            except Exception:  # noqa: BLE001
                pass
    todo = [n for n in names if n not in done]
    print(f"待查 {len(todo)}", flush=True)
    hit = 0
    t0 = time.time()
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20.0,
                      follow_redirects=True) as cli, out.open("a", encoding="utf-8") as f:
        for i, n in enumerate(todo, 1):
            urls: list[str] = []
            titles: list[str] = []
            try:
                r = cli.get("https://cn.bing.com/search", params={"q": f"{n} 招聘官网"})
                if r.status_code == 200:
                    urls = [u for u in HREF.findall(r.text) if not any(j in u for j in JUNK)]
                    titles = [m.group(0) for m in TITLE_PAT.finditer(r.text)][:8]
            except Exception:  # noqa: BLE001
                pass
            rec = {"company": n, "titles": titles, "urls": urls[:12]}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            if titles:
                hit += 1
                print(f"HIT {n:14s} {titles[:2]}", flush=True)
            time.sleep(1.05)
            if i % 40 == 0:
                print(f"... {i}/{len(todo)} {time.time() - t0:.0f}s 命中 {hit}", flush=True)
    print(f"完成 {len(todo)}，命中 {hit}，用时 {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
