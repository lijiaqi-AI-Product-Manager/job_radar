"""旧版北森门户（`xxx.zhiye.com`，非 `/api` 版）列表页解析。

背景：`sources/beisen_legacy.yaml` 里 23 个源全部 `302 -> /404`，因为**新版列表接口在旧门户
上不存在**。但旧门户本身是好的——它的列表页是服务端渲染的 HTML 表格，
`/social/?PageIndex=N` 与 `/campus/?PageIndex=N` 都能直接翻页，岗位名、地点、发布时间
全在 HTML 里。所以「接口报 404」不等于「没数据」，只是要换一条路读。

页面结构（2026-10-26 实测 `yumchina.zhiye.com`）：

    <td class="tableleft joblsttitle">
      <a title="必胜客餐厅储备经理-诸暨" jobAdId="310095098"
         href="/zpdetail/310095098?PageIndex=1">必胜客餐厅储备经理-诸暨</a>
    </td>
    <td class="tableleft joblsttitle" title="必胜客">必胜客</td>
    <td title="浙江省-绍兴市-诸暨市" class="tableleft joblsttitle">浙江省-绍兴市-...</td>
    <td class="tableleft joblsttitle">2022-11-18</td>

地点是「省-市-区」用 `-` 连，标题列被截断（`...`）时以 `title` 属性为准。
"""
from __future__ import annotations

import re

ROW = re.compile(
    r'<td class="tableleft joblsttitle">\s*'
    r'<a title="(?P<title>[^"]{2,120})"\s+jobAdId="(?P<jid>\d+)"\s*'
    r'href="(?P<href>[^"]+)"',
    re.I | re.S)
CELL = re.compile(r'<td[^>]*class="tableleft joblsttitle"[^>]*>(?P<v>[^<]*)</td>', re.I)
LOC_CELL = re.compile(r'<td[^>]*title="(?P<loc>[^"]+)"[^>]*class="tableleft joblsttitle"', re.I)
DATE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
LAST_PAGE = re.compile(r"_MvcPager_Ctrl\d+_pib\"\)\,(\d+)\)")
PROV_SUFFIX = ("特别行政区", "维吾尔自治区", "壮族自治区", "回族自治区", "自治区", "省")
MUNICIPAL = frozenset("北京 上海 天津 重庆 香港 澳门".split())


def _city(loc: str) -> list[str]:
    """`浙江省-绍兴市-诸暨市` -> ['绍兴']；`北京-北京市` -> ['北京']。只到省就返回空。"""
    out: list[str] = []
    for seg in re.split(r"[-/、,，·]", loc or ""):
        seg = seg.strip()
        if not seg:
            continue
        for suf in PROV_SUFFIX:
            if seg.endswith(suf):
                seg = seg[: -len(suf)]
                break
        seg = seg[:-1] if seg.endswith("市") else seg
        if not seg or len(seg) > 12:
            continue
        if seg in MUNICIPAL:
            out.append(seg)
        elif seg not in out:
            out.append(seg)
    # 第一个是省（已剥后缀），只保留看起来像市的：直辖市/长度 2-4
    if len(out) >= 2 and out[0] not in MUNICIPAL:
        return out[1:2]
    return out[:1] if out and out[0] in MUNICIPAL else []


def parse_list(html: str) -> list[dict]:
    """从旧版列表页抽岗位：{source_job_id, title, url_path, brand, city, publish_at}。"""
    rows: list[dict] = []
    for m in ROW.finditer(html):
        title = m.group("title").strip()
        path = m.group("href")
        # 岗位所在的 <tr> 里还有品牌/地点/日期三个 td，从匹配位置往后取一段
        tail = html[m.end(): m.end() + 1200]
        end = tail.find("</tr>")
        if end > 0:
            tail = tail[:end]
        cells = [c.group("v").strip() for c in CELL.finditer(tail)]
        loc = LOC_CELL.search(tail)
        date = DATE.search(tail)
        rows.append({
            "source_job_id": m.group("jid"),
            "title": title,
            "url_path": path,
            "brand": cells[0] if cells else "",
            "city": _city(loc.group("loc") if loc else ""),
            "publish_at": f"{date.group(1)}-{date.group(2)}-{date.group(3)}" if date else None,
        })
    # 去重：同一页同一个 jid 只留一条
    seen: set[str] = set()
    out = []
    for r in rows:
        if r["source_job_id"] in seen:
            continue
        seen.add(r["source_job_id"])
        out.append(r)
    return out


def last_page(html: str) -> int:
    """从 MvcPager 的跳转 JS 里取**最后一页的页码**；取不到返回 1。

    实测 `_MvcPager_GoToPage(...,161)` 里的 161 在只有 1 页的页面上也出现，
    所以还要看页码链接 `<a ...>161</a>` 是否存在；存在才采信。
    """
    if not re.search(r"piblink[\"']?[^>]*>\s*<a[^>]*href=\"/[^\"]*PageIndex=\d+\"", html):
        return 1
    m = LAST_PAGE.search(html)
    return (int(m.group(1)) + 1) if m else 1
