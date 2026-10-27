"""招聘日历扩量的最后一道闸：把「入口页不属于这家公司」的条目剔掉。

为什么需要：搜索引擎 + 官网反查能找到大量真实招聘站，但也会串味——2026-10-26 实测出现过
「微博 → 网易校园招聘」「罗兰贝格 → 容百集团」「高通 → E 聘网」「特斯拉 → 高校统一认证」。
宁可这家公司不进日历，也不能挂一条别家的链接（那是硬错误）。

判定层级（只用已抓到的证据，不再发请求）：
A. 硬剔除：高校就业网 / 政府就业平台 / 招聘平台 / UGC / 财经站（这些是**第三方**，不能当来源）；
B. 冲突剔除：同一 URL 被多家公司认领，且标题里的公司名不是本案公司 → 张冠李戴，剔除；
C. 保留：标题含公司名、或域名/路径含公司拼音或英文 token、或 ATS 租户路径含 token；
D. 其余（标题为空、域名是英文品牌词但证据只来自搜索排序）→ **保留但打标 low_conf**，
   因为「jobs.bytedance.com」「jobs.mihoyo.com」这类真实官网就是这种形态，一刀切会误杀。

用法：
    python3 work/resolve_conflicts.py
输出：work/careers_final.jsonl + work/careers_rejected.jsonl
"""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 第三方：高校就业网、政府就业平台、招聘平台、UGC、财经站。注意只匹配**主机**，
# 且公司自有招聘站（talent.baidu.com / jobs.bytedance.com）不能被误伤。
THIRD_HOST = re.compile(
    r"(\.edu\.cn|\.edu$|^career\.(uibe|nankai|muc|cup|xidian|xujc|ynu|sdu|buct|shiep|neuq)\.|"
    r"job\.(sjtu|hdu|xidian|ynu)\.|^zhaopin\.com|^www\.zhaopin|51job|liepin|^\.?(m\.)?zhipin|nowcoder|"
    r"kanzhun|yingjiesheng|shixiseng|jobui|^www\.dajie|eet-china|gxrc|chinahr|gaoxiaojob|^www\.ejob|"
    r"chinajob|offcn|gwy\.com|aiqicha|^baike\.|^zhuanlan\.|sohu\.com|^www\.163|^news\.|^ir\.|"
    r"^zhihu|weibo\.com|douban|toutiao|csdn|jianshu|^wiki|eastmoney|rc\.qingdao\.gov)", re.I)


def main() -> None:
    rows = [json.loads(s) for s in
            (ROOT / "work/careers_confirmed.jsonl").read_text(encoding="utf-8").splitlines() if s.strip()]

    owners: dict[str, set[str]] = defaultdict(set)
    titles: dict[str, set[str]] = defaultdict(set)
    TOKENS: dict[str, list[str]] = {}
    for r in rows:
        TOKENS[r["company"]] = r.get("tokens") or []
        b = r.get("best")
        if b:
            owners[b["url"]].add(r["company"])
            if b.get("title"):
                titles[b["url"]].add(b["title"])

    final, rejected = [], []
    for r in rows:
        c = r["company"]
        b = r.get("best")
        if not b:
            continue
        u, t = b["url"], (b.get("title") or "")
        host = re.sub(r"^https?://", "", u).split("/")[0].lower()

        if THIRD_HOST.search(host) or "/wp-content/" in u:
            rejected.append({**r, "reason": "third_party"})
            continue

        toks = r.get("tokens") or []
        flat = re.sub(r"[^a-z0-9]", "", u.lower())
        host_flat = re.sub(r"[^a-z0-9]", "", host)
        name_hit = c in t or (len(c) >= 3 and c[:3] in t)
        token_hit = any(tok in flat for tok in toks)
        # 域名归属权：token 直接出现在域名里，这是最强的归属证据
        host_own = any(len(tok) >= 3 and tok in host_flat for tok in toks)

        # 冲突：同一 URL 被多家公司认领
        others = owners[u] - {c}
        if others and not name_hit:
            # 先判断域名归谁：如果只有本案公司的 token 在域名里，本案胜出
            rivals_own = []
            for o in others:
                o_toks = TOKENS.get(o) or []
                if any(len(x) >= 3 and x in host_flat for x in o_toks):
                    rivals_own.append(o)
            if host_own and not rivals_own:
                final.append({**r, "conf": "high", "note": "host_owned"})
                continue
            if rivals_own and not host_own:
                rejected.append({**r, "reason": "conflict:" + ",".join(sorted(rivals_own))})
                continue
            rejected.append({**r, "reason": "conflict:" + ",".join(sorted(others))})
            continue

        if name_hit or token_hit:
            final.append({**r, "conf": "high"})
        else:
            final.append({**r, "conf": "low"})

    (ROOT / "work/careers_final.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in final), encoding="utf-8")
    (ROOT / "work/careers_rejected.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rejected), encoding="utf-8")

    print("final", len(final), Counter(x["conf"] for x in final))
    print("rejected", len(rejected), Counter(x["reason"].split(":")[0] for x in rejected))
    for x in rejected[:25]:
        print("  DROP", x["company"], "|", x["best"]["url"][:60], "|", (x["best"].get("title") or "")[:26],
              "|", x["reason"][:40])
    print("--- low conf 示例 ---")
    for x in [y for y in final if y["conf"] == "low"][:15]:
        print("  LOW", x["company"], "|", x["best"]["url"][:60], "|", (x["best"].get("title") or "")[:26])


if __name__ == "__main__":
    main()
