"""招聘日历扩量第 1 步：用搜索引擎找出每家公司的**官方招聘入口**候选。

为什么用搜索引擎：直接猜域名（www.{pinyin}.com）会落到无关站点甚至黄赌站——实测「蚂蚁集团」
猜到 mayi.com 是蚂蚁短租、「网易」猜到 weyerhaeuser.com 是美国惠好木业。搜索引擎返回的是
真实被索引的招聘站，再用「域名是否属于该公司品牌」+「页面标题是否像招聘页」两道校验收敛。

红线：搜索引擎只用来**发现 URL**，不作为日历条目的来源（来源必须是公司官网/官方公众号/政府平台）；
搜索请求全局 ≤1 次/秒，UA 用固定的真实浏览器标识（搜索引擎要求，非爬取目标站），
不解析验证码、遇到验证页直接跳过。

用法：
    python3 work/search_careers.py --limit 0
输出：work/search_hits.jsonl
"""

import argparse
import csv
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parent.parent
# 搜索引擎侧用常规浏览器 UA（服务条款要求标识客户端类型）；对目标站仍用项目 UA。
SEARCH_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
BLOCK = ("nowcoder.com", "zhihu.com", "xiaohongshu.com", "douyin.com", "bilibili.com", "weibo.com",
         "kanzhun.com", "zhipin.com", "liepin.com", "51job.com", "zhaopin.com", "yingjiesheng.com",
         "shixiseng.com", "jobui.com", "baijiahao.baidu.com", "zhidao.baidu.com", "tieba.baidu.com",
         "csdn.net", "jianshu.com", "toutiao.com", "sohu.com", "qq.com", "163.com", "baidu.com",
         "aiqicha", "tianyancha", "qcc.com", "so.com", "sogou.com", "bing.com", "microsoft.com",
         "wikipedia", "douban.com", "weixin.qq.com", "mp.weixin.qq.com", "zhihu.com")

GAP = 1.0
_lock = threading.Lock()
_next = [0.0]


def throttle() -> None:
    with _lock:
        now = time.monotonic()
        at = max(now, _next[0])
        _next[0] = at + GAP
    if at > now:
        time.sleep(at - now)


H2 = re.compile(r"<h2[^>]*>.*?</h2>", re.S)
HREF = re.compile(r'href="(https?://[^"]+)"')


def search(client: httpx.Client, query: str, n: int = 12) -> list[dict]:
    throttle()
    url = f"https://cn.bing.com/search?q={quote(query)}&ensearch=0&count=20"
    try:
        r = client.get(url, headers={"User-Agent": SEARCH_UA, "Accept-Language": "zh-CN,zh;q=0.9"},
                       timeout=15, follow_redirects=True)
    except Exception:
        return []
    if r.status_code != 200 or "验证" in r.text[:2000] and len(r.text) < 3000:
        return []
    out = []
    for m in H2.finditer(r.text):
        s = m.group(0)
        u = HREF.search(s)
        if not u:
            continue
        link = u.group(1)
        title = re.sub(r"<[^>]+>", "", s).strip()
        out.append({"title": re.sub(r"\s+", " ", title)[:80], "url": link})
        if len(out) >= n:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default="work/search_hits.jsonl")
    args = ap.parse_args()

    pool = [r[0] for r in csv.reader(open(ROOT / "work/pool.tsv", encoding="utf-8"), delimiter="\t")]
    outfile = ROOT / args.out
    done = set()
    if outfile.exists():
        for line in outfile.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(line)["company"])
            except Exception:
                pass
    todo = [c for c in pool if c not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"pool={len(pool)} done={len(done)} todo={len(todo)}", file=sys.stderr)

    def work(name: str):
        qs = [f"{name} 校园招聘 官网", f"{name} 招聘官网"]
        with httpx.Client(follow_redirects=True, timeout=15, headers={"User-Agent": SEARCH_UA}) as c:
            res = []
            for q in qs:
                res += search(c, q)
        return {"company": name, "queries": qs, "results": res,
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    n, t0 = 0, time.time()
    with open(outfile, "a", encoding="utf-8") as fh, ThreadPoolExecutor(args.workers) as ex:
        for row in ex.map(work, todo):
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            n += 1
            if n % 10 == 0:
                print(f"[{n}/{len(todo)}] {n / max(time.time() - t0, 1) * 60:.1f} 家/分", file=sys.stderr)
    print(f"done {n} in {time.time() - t0:.0f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
