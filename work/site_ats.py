"""官网 → ATS 反向发现：不再从「公司名」猜 ATS slug，而是从**搜索结果里已经出现的 URL**
反推出「这家公司用的是哪个招聘系统」。

为什么换算法（2026-10-27 实测教训）：
  - 猜 `{拼音}.zhiye.com` / `{拼音}.jobs.feishu.cn` 命中率已掉到 ~1%，
    因为多数公司租户是随机串或英文品牌名，拼音根本猜不到；
  - 但搜索结果本身就把答案摆在眼前：`hr.360.cn`（自建）、`360campus.zhiye.com`（北森）、
    `keep.jobs.feishu.cn`（飞书）——**每家公司命中的 URL 里往往就有它自己的招聘站**。
    老版脚本按 host 聚合后只保留了「官网主页」，把 `hr.360.cn` 这类子域和 ATS 域名
    当第三方丢掉了，等于把答案扔了。

新算法（三步，全部只读公开页面，1 rps/主机）：
  1. **归属校验**：对每条候选 URL，拉一次页面，判断「这家公司的名字是否出现在
     title / 首屏正文 / 路径 slug」里。只有验过的才算它家的（避免把竞品、媒体稿、
     供应商站点算进来）。ATS 域名（zhiye/hotjob/feishu…）额外用 `tenant` 段与
     公司拼音/英文名比对，作为第二条证据。
  2. **按 ATS 归类**：域名特征 → 适配器名（beisen/hotjob/feishu_atsx/…）；
     都不像但页面里有 `webapi`/`_nuxt` 指纹 → `nuxt`；剩下归 `self`（自建站）。
  3. **输出可直接落地的参数**：`tenant` / `host` / `entry`，写 YAML 时不用再猜。

用法：
    python3 work/site_ats.py --out /tmp/exp/site1.jsonl --workers 10
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
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "work"))
sys.path.insert(0, str(ROOT / "src"))

import beisen_tenant_sweep as bb  # noqa: E402

from jobradar.adapters.base import USER_AGENT  # noqa: E402

# 单字拼音表（beisen_tenant_sweep 同款缓存），用来判断 ATS 租户段是不是这家公司的名字
PY: dict[str, str] = bb.load_pinyin()

# 纯第三方：媒体/百科/电商/词典/聚合站。这些域名**永不可能**是公司自己的招聘站。
THIRD_PARTY = (
    "baidu.com", "zhihu.com", "sohu.com", "sina.com", "qq.com", "163.com", "toutiao.com",
    "thepaper.cn", "people.com.cn", "gov.cn", "eastmoney.com", "zhipin.com", "zhaopin.com",
    "51job.com", "liepin.com", "lagou.com", "yingjiesheng.com", "shixiseng.com",
    "jd.com", "tmall.com", "taobao.com", "1688.com", "amazon.", "wikipedia.org",
    "hanyuguoxue.com", "hgcha.com", "zdic.net", "chagushici.com", "gushici.net",
    "shidianguji.com", "revised.moe.edu.tw", "zgbk.com", "chsi.com.cn", "gwy.com",
    "douban.com", "weibo.com", "xiaohongshu.com", "bilibili.com", "youtube.com",
    "niuqizp.com", "nowcoder.com", "haitou.cc", "yingjiewang.com", "xiaoyuanzhaopin.com",
    "jobui.com", "ganji.com", "58.com", "zhaopin.cn", "dajie.com", "chinahr.com",
    "ejob100.com", "gzstv.com", "csdn.net", "jianshu.com", "cnblogs.com",
    "qcc.com", "tianyancha.com", "aiqicha.baidu.com", "linkedin.com",
    # 高校就业网：上面挂的是「来校宣讲的企业」的岗位页，不是企业自己的招聘站
    # （万华化学实测命中 myjob.dlmu.edu.cn/campus/view/id/…，是大连海事大学的就业网）
    ".edu.cn", ".edu.", "myjob.", "jiuye.", "job.sdu", "campus.", "scc.", "careercenter.",
    # 公考/考研/求职培训站的「XX招聘公告」页（今日招聘、中公、高顿、上岸等实测命中）
    "jrzp.com", "offcn.com", "eoffcn.com", "gaodun.com", "huatu.com", "zgjsks.com",
    "shanganclaw.com", "chinagwy.org", "gktong.com", "kaoyan.com", "chsi.",
    "zhaopin.xin", "qiuzhi.com", "shixi.com", "liebiao.com", "hrdchina.com",
    # 2026-10-27 site_ats2 深挖时暴露的培训/求职平台：upcv.tech 是「UP求职」简历平台、
    # fenbi.com 是粉笔题库、gaoxiaojob.com 是高校招聘信息站、shiyanjia 是科研服务平台
    "upcv.tech", "fenbi.com", "gaoxiaojob.com", "shiyanjia.com", "hahazhao.com",
    "shanganclaw.com", "bendibao.com", "eoffcn.com",
    "mostshine.com", "sa.offcn.com", "chinapost.com.cn", "zhaopin.sdu.edu.cn",
    ".com.cn/announcement", "eol.cn", "xiangrikui.com", "iedu.cn",
)

# ATS 域名特征 → 适配器名。命中 host 任意一段即认。
ATS_SIGNS = (
    ("jobs.feishu.cn", "feishu_atsx"),
    ("zhiye.com", "beisen"),
    ("btnc.cn", "beisen"),
    ("hotjob.cn", "hotjob"),
    ("mokahr.com", "moka"),
    ("italent.cn", "italent"),
    ("myworkdayjobs.com", "workday"),
    ("workday.com", "workday"),
    ("successfactors", "sap"),
    ("taleo.net", "taleo"),
    ("icims.com", "icims"),
    ("smartrecruiters.com", "smartrecruiters"),
    ("lever.co", "lever"),
    ("greenhouse.io", "greenhouse"),
    ("dayee.com", "dayee"),
    ("dayiinc.com", "dayee"),
    ("wintalent", "wintalent"),
    ("nrecruit", "nrecruit"),
    ("zhaopin.com", "zhaopin"),
    ("51job.com", "51job"),
    ("liepin.com", "liepin"),
    ("lagou.com", "lagou"),
    ("careercloud", "careercloud"),
)

# 招聘入口的路径词 / 锚文本词
ENTRY_WORDS = ("job", "career", "zhaopin", "hr", "join", "recruit", "talent", "zhiye",
               "campus", "xiaozhao", "shezhao", "hiring", "employ", "rencai", "zhaoping")
ENTRY_TEXT = ("招聘", "加入我们", "加入", "人才", "careers", "jobs", "工作机会", "招贤")
AUTO_SUBDOMAINS = ("hr", "job", "jobs", "zhaopin", "career", "careers", "recruit", "talent")

NAME_NOISE = ("股份有限公司", "有限责任公司", "有限公司", "集团", "控股", "科技", "技术",
              "（中国）", "(中国)", "中国", "公司", "国际", "控股集团")


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


def core_name(name: str) -> str:
    n = name
    for w in NAME_NOISE:
        n = n.replace(w, "")
    return n.strip() or name


def title_of(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def page_text(html: str) -> str:
    t = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<style.*?</style>", " ", t, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))


# 页面里必须出现这些词，才算「招聘入口」而不是恰好路径带 hr/job 的普通页面
JOB_HINT = ("职位", "岗位", "招聘", "投递", "简历", "任职", "job", "career", "position",
            "vacanc", "hiring", "apply", "招聘职位", "校园招聘", "社会招聘", "加入")
# 首页/公司介绍页不是招聘入口，哪怕 title 里有「加入」
NOT_ENTRY_PATH = ("/about", "/gywm", "/lxwm", "/contact", "/news", "/xwzx", "/company",
                  "/events", "/event", "/activity", "/struct", "/gsjg", "/aboutus")


def looks_like_recruit(html: str, url: str) -> bool:
    """路径或页面内容至少要有一处明确指向「招聘」，才算招聘入口。

    2026-10-27 教训：`yidiandian-tea.com/xinwenzx/324.html`（新闻稿标题里带「招聘」）、
    `tcltech.com/about`（公司介绍页）都被旧判据收进来了。两条一起卡：
      ① 路径不能是 about/news/contact 这类介绍页；
      ② 页面里至少 3 处招聘词（单次出现通常是导航栏里的一个链接）。
    """
    path = (urlparse(url).path or "/").lower()
    if any(path.startswith(p) or p in path for p in NOT_ENTRY_PATH):
        return False
    low = html.lower()
    return sum(low.count(w) for w in JOB_HINT) >= 3


def classify(url: str, html: str = "", title: str = "") -> str:
    h = host_of(url)
    for sign, ats in ATS_SIGNS:
        if sign in h:
            return ats
    if html:
        low = html.lower()
        if "webapi/api/connect/token" in low or "_nuxt/" in low:
            return "nuxt"
    if re.search(r"(jobs?|careers?|zhaopin|hr|recruit|join)", h) or \
            any(w in title for w in ("招聘", "加入", "career", "job", "Career", "Job")):
        return "self"
    return ""


def owns(url: str, html: str, name: str, ats: str) -> bool:
    """这条 URL 是不是**这家公司**的招聘入口。

    证据优先级：ATS 域名的 tenant 段 == 公司拼音/英文名 > 公司名出现在 title/首屏 >
    公司名出现在 URL 路径。中文页面 title 常写成「加入XX」或「XX招聘」，都算命中。
    """
    core = core_name(name)
    if len(core) < 2:
        return False
    h = host_of(url)
    path = urlparse(url).path or ""
    if ats and ats != "self":
        # ATS 子域第一段就是 tenant：zhiye/hotjob/feishu 都适用
        seg = h.split(".")[0]
        py = bb.candidates(name, PY)[:6]
        if seg in py or seg.lower() in (core.lower(), name.lower()):
            return True
    head = (title_of(html) + " " + page_text(html)[:2500]).replace(" ", "")
    if core in head:
        return True
    squash = re.sub(r"[|\-–—_·•,，、()（）\s]", "", head)
    if core in squash:
        return True
    # URL 里出现公司拼音（hr.360.cn 里的 360、keep.jobs.feishu.cn 里的 keep）
    low_url = (h + path).lower()
    return any(len(c) >= 3 and c in low_url for c in bb.candidates(name, PY)[:3])


def find_entries(html: str, base: str) -> list[str]:
    out: list[str] = []
    for m in re.finditer(r'<a[^>]+href="([^"#{}]+)"[^>]*>(.*?)</a>', html, re.I | re.S):
        href, txt = m.group(1).strip(), re.sub(r"<[^>]+>", "", m.group(2))
        txt = re.sub(r"\s+", " ", txt).strip()[:30]
        if href.startswith(("mailto:", "javascript:", "tel:")):
            continue
        from urllib.parse import urljoin
        try:
            u = urljoin(base, href)
        except ValueError:
            continue
        hu = host_of(u)
        if not hu or is_third_party(hu):
            continue
        path = (urlparse(u).path or "/").lower()
        if any(w in path for w in ENTRY_WORDS) or any(w in txt for w in ENTRY_TEXT):
            out.append(u.split("?")[0][:150])
    return list(dict.fromkeys(out))[:8]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/exp/site1.jsonl")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--inputs", default="/tmp/exp/brand.jsonl,/tmp/exp/brand2.jsonl")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    # 1) 汇总每家公司的**全部**候选 URL（不再只留 host），并按「看起来像招聘入口」优先排序
    cands: dict[str, list[str]] = defaultdict(list)
    for f in a.inputs.split(","):
        p = Path(f)
        if not p.exists():
            print(f"[warn] 缺输入 {f}", flush=True)
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
                cands[rec["company"]].append(u.split("?")[0][:150])

    def rank(u: str) -> int:
        h, path = host_of(u), (urlparse(u).path or "").lower()
        ats = classify(u)
        if ats and ats != "self":
            return 0                      # ATS 域名最值钱
        if any(w in h for w in ("hr.", "job", "career", "zhaopin", "recruit")):
            return 1
        if any(w in path for w in ENTRY_WORDS):
            return 2
        return 3

    allnames = list(cands)
    out = Path(a.out)
    done: set[str] = set()
    if out.exists():
        for ln in out.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(ln)["company"])
            except Exception:  # noqa: BLE001
                pass
    todo = [(c, sorted(set(cands[c]), key=rank)[:6]) for c in allnames if c not in done]
    if a.limit:
        todo = todo[: a.limit]
    print(f"待查 {len(todo)} 家（已有 {len(done)}），{a.workers} 路并行", flush=True)

    lock = threading.Lock()
    fh = out.open("a", encoding="utf-8")
    t0 = time.time()
    stat = {"hit": 0}

    def work(item: tuple[str, list[str]]) -> None:
        comp, us = item
        res: dict = {"company": comp, "ats": "", "tenant": "", "host": "", "entry": "", "conf": ""}
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=10.0,
                          follow_redirects=True) as cli:
            for u in us:
                ats = classify(u)
                try:
                    r = cli.get(u)
                except Exception:  # noqa: BLE001
                    continue
                if r.status_code >= 400 or len(r.text or "") < 400:
                    continue
                if not ats:
                    ats = classify(u, r.text, title_of(r.text))
                if not ats:
                    continue
                if not owns(u, r.text, comp, ats):
                    continue
                if ats == "self" and not looks_like_recruit(r.text, str(r.url)):
                    continue
                h = host_of(u)
                res.update(ats=ats, host=h, entry=str(r.url)[:150],
                           conf=title_of(r.text)[:50])
                if ats in ("beisen", "hotjob", "feishu_atsx", "italent", "dayee",
                           "wintalent", "nrecruit", "moka"):
                    res["tenant"] = h.split(".")[0]
                break
        with lock:
            fh.write(json.dumps(res, ensure_ascii=False) + "\n")
            fh.flush()
            if res["ats"]:
                stat["hit"] += 1
                print(f"HIT {comp:16s} {res['ats']:12s} {res['host']:32s} {res['conf'][:26]}",
                      flush=True)

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(work, x) for x in todo]
        for i, fu in enumerate(futs, 1):
            fu.result()
            if i % 50 == 0:
                el = time.time() - t0
                print(f"... {i}/{len(todo)} {el:.0f}s 命中 {stat['hit']} ({el / i:.2f}s/家)",
                      flush=True)
    fh.close()
    print(f"完成 {len(todo)}：命中 {stat['hit']} 家，用时 {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
