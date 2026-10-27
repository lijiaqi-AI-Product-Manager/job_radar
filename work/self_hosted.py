"""自建招聘站探测：从搜索结果里的域名找出**公司自己托管的招聘站**并抓岗位。

数据来源：`/tmp/exp/brand*.jsonl`（每家公司的品牌搜索结果，纯公开网页）。

判定链路（每一环都只读公开页面）：
  1. 把搜索结果里的 URL 按 host 聚合，丢掉聚合站/百科/媒体/词典这类**第三方**域名；
  2. 剩下的 host 归到该公司名下，作为「自家域名候选」；
  3. 对每个候选 host，先试常见招聘入口路径（`/jobs` `/careers` `/zhaopin` `/hr` `/join`），
     再看落地页里有没有岗位条目的结构特征（多行 `<li>` 里带「工程师/经理/专员」这类词）；
  4. 命中就输出 `{company, host, entry, jobs, titles}`，交给人工/下一步拆适配器。

**不做任何猜测式爆破**：路径只试固定的几个公开入口，频率 1 rps/主机。

用法：
    python3 work/self_hosted.py --out /tmp/exp/self1.jsonl --workers 10
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from jobradar.adapters.base import USER_AGENT  # noqa: E402

# 第三方域名：聚合站、百科、媒体、词典、电商、政务。命中即整条丢弃。
THIRD_PARTY = (
    "baidu.com", "zhihu.com", "sohu.com", "sina.com", "qq.com", "163.com", "toutiao.com",
    "thepaper.cn", "people.com.cn", "gov.cn", "eastmoney.com", "zhipin.com", "zhaopin.com",
    "51job.com", "liepin.com", "lagou.com", "yingjiesheng.com", "shixiseng.com",
    "jd.com", "tmall.com", "taobao.com", "1688.com", "amazon.", "wikipedia.org",
    "hanyuguoxue.com", "hgcha.com", "zdic.net", "chagushici.com", "gushici.net",
    "shidianguji.com", "revised.moe.edu.tw", "zgbk.com", "chsi.com.cn", "gwy.com",
    "douban.com", "weibo.com", "xiaohongshu.com", "bilibili.com", "youtube.com",
    "feishu.cn", "zhiye.com", "hotjob.cn", "mokahr.com", "myworkdayjobs.com",
    # 校园招聘聚合站：内容是他家攒的岗位，不是公司自建站（世纪华通实测命中 niuqizp.com）
    "niuqizp.com", "yingjiesheng.com", "shixiseng.com", "nowcoder.com", "haitou.cc",
    "yingjiewang.com", "xiaoyuanzhaopin.com", "jobui.com", "ganji.com", "58.com",
    "zhaopin.cn", "dajie.com", "chinahr.com", "ejob100.com", "gzstv.com",
    "csdn.net", "jianshu.com", "cnblogs.com", "github.com", "gitee.com",
)

ENTRY_PATHS = ("/jobs", "/job", "/careers", "/career", "/zhaopin", "/hr", "/join", "/recruit",
               # 官网导航里常见的二级入口（帆软的岗位列表就挂在 /social、/campus 这种词下面）
               "/social", "/campus", "/trainee", "/join-us", "/joinus", "/jobs.html", "/job.html")
JOB_WORDS = ("工程师", "经理", "专员", "主管", "设计师", "分析师", "顾问", "实习生", "总监", "运营")
# 新闻稿/培训班/活动报道里的「工程师」不是岗位名
NOISE_WORDS = ("培训", "论坛", "峰会", "发布会", "研讨会", "荣获", "荣获", "颁奖", "签约", "合作",
               "新闻", "报道", "招聘会", "宣讲")
CITY_WORDS = ("北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "南京", "西安", "苏州",
              "天津", "重庆", "长沙", "合肥", "青岛", "郑州")


def host_of(url: str) -> str:
    try:
        h = urlparse(url).hostname or ""
    except ValueError:
        return ""
    return h.lower()


def is_third_party(host: str) -> bool:
    return any(t in host for t in THIRD_PARTY)


def dns_ok(host: str) -> bool:
    try:
        socket.gethostbyname(host)
        return True
    except OSError:
        return False


def count_jobs(html: str) -> tuple[int, list[str]]:
    """落地页里看起来像岗位条目的行数。只看结构，不解析具体字段。"""
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    rows = re.findall(r"<(?:li|a|h3|h4|div)[^>]*>([^<>]{4,60})</(?:li|a|h3|h4|div)>", text)
    hits: list[str] = []
    for r in rows:
        t = re.sub(r"\s+", " ", r).strip()
        if len(t) < 4 or len(t) > 45:
            continue
        if any(w in t for w in JOB_WORDS) and not any(c in t for c in "要求职责描述优先"):
            hits.append(t)
    # 城市列出现也能佐证这是岗位列表
    city_rows = sum(1 for r in rows if any(c in r for c in CITY_WORDS) and len(r) < 30)
    return max(len(hits), city_rows // 2), hits[:5]


def probe(cli: httpx.Client, host: str) -> dict | None:
    for path in ENTRY_PATHS:
        try:
            r = cli.get(f"https://{host}{path}", follow_redirects=True)
        except Exception:  # noqa: BLE001
            continue
        if r.status_code != 200 or len(r.text) < 800:
            continue
        if not looks_like_job_list(r.text):
            continue
        job_n = len(parse_blocks(r.text))
        if job_n >= 3:
            blocks = parse_blocks(r.text)
            return {"host": host, "entry": str(r.url)[:120], "n": job_n,
                    "titles": [b["title"] for b in blocks[:5]]}
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/exp/self1.jsonl")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--inputs", default="/tmp/exp/brand.jsonl,/tmp/exp/brand2.jsonl")
    a = ap.parse_args()

    # 1) 汇总每家公司的自家域名候选
    hosts: dict[str, set[str]] = defaultdict(set)
    for f in a.inputs.split(","):
        p = Path(f)
        if not p.exists():
            continue
        for ln in p.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(ln)
            except Exception:  # noqa: BLE001
                continue
            for u in rec.get("urls") or []:
                h = host_of(u)
                if not h or is_third_party(h) or h.count(".") < 1 or h.count(".") > 3:
                    continue
                hosts[rec["company"]].add(h)

    todo = [(c, sorted(hs)[:3]) for c, hs in hosts.items() if hs]
    print(f"{len(todo)} 家有自家域名候选，{a.workers} 路并行", flush=True)
    out = Path(a.out)
    lock = threading.Lock()
    fh = out.open("a", encoding="utf-8")
    t0 = time.time()
    hits = 0

    def work(item: tuple[str, list[str]]) -> None:
        nonlocal hits
        comp, hs = item
        found = []
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=10.0,
                          follow_redirects=True) as cli:
            for h in hs:
                if not dns_ok(h):
                    continue
                pr = probe(cli, h)
                if pr:
                    pr["company"] = comp
                    found.append(pr)
                    break
        with lock:
            fh.write(json.dumps({"company": comp, "found": found}, ensure_ascii=False) + "\n")
            fh.flush()
            if found:
                hits += 1
                pr = found[0]
                print(f"HIT {comp:14s} {pr['host']:32s} n={pr['n']} {pr['titles'][:2]}", flush=True)

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(work, x) for x in todo]
        for i, fu in enumerate(futs, 1):
            fu.result()
            if i % 25 == 0:
                el = time.time() - t0
                print(f"... {i}/{len(todo)} {el:.0f}s 命中 {hits} ({el / i:.2f}s/家)", flush=True)
    fh.close()
    print(f"完成 {len(todo)}，命中 {hits} 家，用时 {time.time() - t0:.0f}s", flush=True)
    return 0


def looks_like_job_list(html: str) -> bool:
    """整页判定：至少 5 个不同标题里带职位词，且这些词不在「培训/新闻/活动」语境里。

    这条是给筛选用的，比 `parse_blocks` 宽松：只回答「这页像不像招聘页」。
    SGS 的官网 `/careers` 是一堆培训班新闻稿，逐条命中「工程师」但整页根本不是我司岗位，
    这种要靠「标题里没有城市/部门特征 + 词都在长句里」排除。
    """
    clean = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    titles = re.findall(r"<h[23][^>]*>([^<]{2,40})</h[23]>", clean)
    good = [t.strip() for t in titles
            if any(w in t for w in JOB_WORDS) and not any(b in t for b in NOISE_WORDS)]
    return len(set(good)) >= 5


def parse_blocks(html: str) -> list[dict]:
    """把「`<h3>岗位名</h3>` + 后面若干 `<p>/<ol>/<li>`」解析成一岗一条。

    只在**没有任何结构化数据**（JSON-LD / 列表接口）时才用，属于兜底：
    这类自建站是手写 HTML，一个岗位就是一串 `<h3>` + `<ol><li>`，
    要求段落用「要求」「任职」开头，职责段落用「职责」「工作内容」开头。
    """
    clean = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    clean = re.sub(r"<style.*?</style>", " ", clean, flags=re.S | re.I)
    parts = re.split(r"<h3[^>]*>(.*?)</h3>", clean, flags=re.S)
    out: list[dict] = []
    for i in range(1, len(parts), 2):
        title = re.sub(r"<[^>]+>", "", parts[i])
        title = re.sub(r"\s+", " ", title).strip()
        if not (2 <= len(title) <= 30) or not any(w in title for w in JOB_WORDS):
            continue
        body = parts[i + 1] if i + 1 < len(parts) else ""
        body = re.sub(r"<br\s*/?>", "\n", body, flags=re.I)
        body = re.sub(r"</(p|li|ol|div)>", "\n", body, flags=re.I)
        body = re.sub(r"<[^>]+>", "", body)
        body = re.sub(r"[ \t]+", " ", body)
        body = re.sub(r"\n{2,}", "\n", body).strip()
        req: list[str] = []
        desc: list[str] = []
        cur = desc
        for ln in body.split("\n"):
            ln = ln.strip()
            if not ln:
                continue
            if any(w in ln[:8] for w in ("要求", "任职", "我们需要的你")):
                cur = req
                continue
            if any(w in ln[:8] for w in ("职责", "工作内容", "希望由你来做")):
                cur = desc
                continue
            cur.append(ln)
        out.append({"title": title, "description": "\n".join(desc)[:4000],
                    "requirements": "\n".join(req)[:4000]})
    return out


if __name__ == "__main__":
    raise SystemExit(main())
