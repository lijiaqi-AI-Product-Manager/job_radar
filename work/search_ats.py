"""用必应反查 ATS 入口：`site:zhiye.com "公司名"` 之类。

为什么值得做：北森/大易/Moka 的租户 slug 是随机串（`fosunpharma`、`xablt`、`kanghong`），
按公司名拼拼音只能覆盖一部分；但搜索引擎索引里有 `{slug}.zhiye.com` 的每一个页面，
`site:` 查询能直接反查出来。实测「以岭药业 site:zhiye.com」能直接命中 `yiling.zhiye.com`。

红线与注意事项：
  - 只读公开搜索结果页，不登录、不伪造 UA、同一搜索引擎主机 ≤1 rps 串行；
  - 搜索引擎**只用于发现入口**，岗位数据仍从公司自己的公开门户抓，不把搜索结果当数据源；
  - **`site:` 语法经常被忽略**（必应会把 `site:` 当普通词，返回一堆公司官网），
    所以结果只当「候选」，最后由调用方逐个验证（门户标题是否对得上公司名）。
  - 每家公司最多 2 条查询，避免把搜索引擎当爬虫刷。

用法：
    python3 work/search_ats.py --in names.txt --out /tmp/s.jsonl
    python3 work/search_ats.py --in names.txt --out /tmp/s.jsonl --resume
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import USER_AGENT  # noqa: E402

ATS_HOSTS = ("zhiye.com", "hotjob.cn", "mokahr.com", "jobs.feishu.cn", "dayee.com",
             "myworkdayjobs.com", "tupu360.com", "avature.net")
HOST_RE = re.compile(
    r"https?://([a-z0-9][a-z0-9.-]{1,50}\.(?:" +
    "|".join(h.replace(".", r"\.") for h in ATS_HOSTS) + r"))", re.I)
HREF = re.compile(r'href="(https?://[^"]+)"', re.I)
# 与 brand_check.JUNK 保持一致：百科/字典/企业信息站/第三方招聘站的页面标题里
# 也满是「XX招聘官网」，不过滤会把入口写成百度百科（实测 1794 次）。
JUNK = (
    "bing.com",
    "microsoft",
    "msn.com",
    "go.microsoft",
    "baike.baidu.com",
    "aiqicha",
    "qcc.com",
    "tianyancha",
    "qixin.com",
    "zhihu.com",
    "hanyuguoxue",
    "hgcha.com",
    "zdic.net",
    "chagushici",
    "gushici.net",
    "shidianguji",
    "zgbk.com",
    "dict.revised.moe",
    "hanyu.baidu",
    "zhipin.com",
    "zhaopin.com",
    "liepin.com",
    "51job.com",
    "yingjiesheng.com",
    "nowcoder.com",
    "maimai.cn",
    "kanzhun.com",
    "shixiseng.com",
    "lagou.com",
    "sohu.com",
    "thepaper.cn",
    "people.com.cn",
    "china.com.cn",
    "163.com",
    "eastmoney.com",
    "chsi.com.cn",
    "gov.cn",
    "wikipedia",
    "baidu.com",
    "douban",
    "weibo",
    "csdn",
    "jianshu",
    "xiaohongshu",
    "bilibili",
)


def search(cli: httpx.Client, query: str) -> list[str]:
    """返回结果页里出现的外链（去重、去搜索引擎自家域名）。"""
    try:
        r = cli.get("https://cn.bing.com/search", params={"q": query, "count": "30"})
    except httpx.HTTPError:
        return []
    if r.status_code != 200:
        return []
    out: list[str] = []
    for h in HREF.findall(r.text):
        if any(j in h for j in JUNK):
            continue
        if h not in out:
            out.append(h)
    # ATS 直链优先排前面（不管 site: 有没有生效）
    ats = [h for h in out if HOST_RE.match(h)]
    rest = [h for h in out if h not in ats]
    return ats + rest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    names = [ln.strip() for ln in Path(args.src).read_text(encoding="utf-8-sig").splitlines() if ln.strip()]
    if args.limit:
        names = names[: args.limit]
    outp = Path(args.out)
    seen: set[str] = set()
    if outp.exists():
        for ln in outp.read_text(encoding="utf-8").splitlines():
            try:
                seen.add(json.loads(ln)["company"])
            except Exception:  # noqa: BLE001
                pass
    todo = [n for n in names if n not in seen]
    print(f"待搜 {len(todo)}（已完成 {len(seen)}）", flush=True)

    hits = 0
    t0 = time.time()
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20.0,
                      follow_redirects=True) as cli, outp.open("a", encoding="utf-8") as f:
        for i, name in enumerate(todo, 1):
            urls: list[str] = []
            for q in (f'{name} 招聘', f'{name} 校园招聘 投递'):
                urls += search(cli, q)
                time.sleep(1.05)  # 同主机 ≤1 rps
            rec = {"company": name, "urls": urls[:40]}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            if any(HOST_RE.match(u) for u in rec["urls"]):
                hits += 1
                with_at = [u for u in rec["urls"] if HOST_RE.match(u)][:3]
                print(f"HIT  {name:16s} {with_at}", flush=True)
            if i % 25 == 0:
                print(f"... {i}/{len(todo)} {time.time() - t0:.0f}s 命中 {hits}", flush=True)
    print(f"完成 {len(todo)}，命中 {hits}，用时 {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
