"""批量探高校就业网：robots -> 首页导航找「招聘信息」-> 列表页能否抽出条目。

输出 work/_campus_probe.json，控制台只打印计数。
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}
OUT = Path("work/_campus_probe.json")

SCHOOLS = {
    "南开": "career.nankai.edu.cn",
    "山东": "job.sdu.edu.cn",
    "河南": "job.zzu.edu.cn",
    "安徽": "job.hfut.edu.cn",
    "山西": "job.tyut.edu.cn",
    "云南": "job.ynu.edu.cn",
    "广西": "job.gxu.edu.cn",
    "贵州": "job.gzu.edu.cn",
    "陕西": "job.xjtu.edu.cn",
    "四川": "job.scu.edu.cn",
    "湖北": "job.whu.edu.cn",
    "湖南": "job.csu.edu.cn",
    "江西": "job.ncu.edu.cn",
    "河北": "job.hbu.edu.cn",
    "辽宁": "job.dlut.edu.cn",
    "吉林": "job.jlu.edu.cn",
    "黑龙江": "job.hit.edu.cn",
    "福建": "job.xmu.edu.cn",
    "甘肃": "job.lzu.edu.cn",
    "新疆": "job.xju.edu.cn",
    "内蒙古": "job.imu.edu.cn",
    "宁夏": "job.nxu.edu.cn",
    "青海": "job.qhu.edu.cn",
    "海南": "job.hainanu.edu.cn",
    "重庆": "job.cqu.edu.cn",
}

NAV_KEYS = ("招聘信息", "招聘公告", "招聘资讯", "职位信息", "招聘需求", "在线招聘", "就业信息")


def strip(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()


def probe(name: str, host: str) -> dict:
    rec: dict = {"name": name, "host": host}
    try:
        with httpx.Client(timeout=12.0, headers=H, follow_redirects=True, verify=False) as c:
            rb = c.get(f"https://{host}/robots.txt")
            rec["robots_status"] = rb.status_code
            if rb.status_code == 200:
                rec["disallow"] = [ln.strip() for ln in rb.text.splitlines() if ln.strip().lower().startswith("disallow")][:10]
            home = c.get(f"https://{host}/")
            rec["home_status"] = home.status_code
            rec["home_bytes"] = len(home.text)
            links = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', home.text, re.S)
            cands = []
            for href, text in links:
                t = strip(text)
                if any(k in t for k in NAV_KEYS):
                    cands.append((t[:16], href))
            rec["nav"] = cands[:4]
            if cands:
                href = cands[0][1]
                url = href if href.startswith("http") else f"https://{host}/" + href.lstrip("/")
                rec["list_url"] = url
                lp = c.get(url)
                rec["list_status"] = lp.status_code
                rec["list_bytes"] = len(lp.text)
                # 通用条目抽取：链接里带 id/内容编号，且文本长度>4
                items = re.findall(r'<a[^>]+href="([^"]*(?:content|info|detail|job|zhaopin|position)[^"]*\d+[^"]*)"[^>]*>(.*?)</a>', lp.text, re.S)
                got, seen = [], set()
                for h2, t2 in items:
                    t2 = strip(t2)
                    if len(t2) < 6 or h2 in seen:
                        continue
                    seen.add(h2)
                    got.append([t2[:50], h2[:110]])
                rec["n_items"] = len(got)
                rec["items"] = got[:12]
    except Exception as exc:  # noqa: BLE001
        rec["error"] = f"{type(exc).__name__}: {exc}"
    return rec


def main() -> None:
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(lambda kv: probe(*kv), SCHOOLS.items()))
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = [r for r in rows if r.get("n_items", 0) > 0]
    print(f"schools={len(rows)} list_ok={len(ok)} -> {OUT}")
    for r in rows:
        print(r["name"], r.get("home_status"), r.get("list_status"), r.get("n_items", 0))


if __name__ == "__main__":
    main()
