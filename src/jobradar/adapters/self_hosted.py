"""单页自建招聘站（`https://公司域名/join` 这类手写 HTML 一页放全部岗位）。

为什么需要它：2026-10-27 用搜索结果里的自家域名扫了 1159 家，
其中相当一部分公司的招聘页**没有列表接口、没有分页、也没有 JSON-LD**——就是一个
`<div class="jd"><h3>岗位名</h3><p>职责…</p><ol><li>…</li></ol></div>` 反复出现。
Keep（`www.calorietech.com/join`）实测：14 个岗位块、职责与要求分段清晰，能直接入库。

解析规则（`parse_blocks`）：
  - 以 `<h3>` 作为岗位边界；标题里必须出现职位词（工程师/经理/专员/主管/设计师/
    分析师/顾问/实习生/总监），否则视为页面小标题跳过；
  - 段落分类：行首 8 字内出现「要求/任职/我们需要的你」→ 要求；出现「职责/工作内容/
    希望由你来做」→ 职责；其余按当前段落归属；
  - 一页一个请求，不翻页；单站点 1 rps 由基类保证。

source.params:
  url: 招聘页地址（必填）
  default_city: 页面不写城市时用的城市（可选；不填就留空，**不猜**）
  recruit_type: 整页统一类型，默认 social（这类页面几乎都是社招）
"""

import re
from collections.abc import Iterator

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import categorize, grad_year_from_text

JOB_WORDS = ("工程师", "经理", "专员", "主管", "设计师", "分析师", "顾问", "实习生", "总监", "运营")
REQ_HEADS = ("要求", "任职", "我们需要的你", "岗位要求", "任职资格")
DESC_HEADS = ("职责", "工作内容", "希望由你来做", "岗位职责", "职位描述")


def parse_blocks(html: str) -> list[dict]:
    """把「`<h3>岗位名</h3>` + 后面若干 `<p>/<ol>/<li>`」解析成一岗一条。"""
    clean = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    clean = re.sub(r"<style.*?</style>", " ", clean, flags=re.S | re.I)
    parts = re.split(r"<h3[^>]*>(.*?)</h3>", clean, flags=re.S)
    out: list[dict] = []
    seen: set[str] = set()
    for i in range(1, len(parts), 2):
        title = re.sub(r"<[^>]+>", "", parts[i])
        title = re.sub(r"\s+", " ", title).strip()
        if not (2 <= len(title) <= 30) or not any(w in title for w in JOB_WORDS):
            continue
        # 这类页面常把同一批岗位渲染两遍（PC 版 + 移动版各一套 DOM），
        # Keep 实测 14 个块里前半和后半完全重复。按标题去重，留第一次出现的。
        if title in seen:
            continue
        seen.add(title)
        body = parts[i + 1] if i + 1 < len(parts) else ""
        body = re.sub(r"<br\s*/?>", "\n", body, flags=re.I)
        body = re.sub(r"</(p|li|ol|div|h4|h5)>", "\n", body, flags=re.I)
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
            # 段落标记可能带前缀（「任职要求：…」「岗位职责：…」），也可能整行就是标记。
            # 只看行首 12 个字，不要求以标记开头（实测有的是「任职要求」直接接正文）。
            head = ln[:12]
            if any(w in head for w in REQ_HEADS):
                cur = req
                if len(ln) <= 12:
                    continue
                # 「任职要求：xxx」把冒号后的正文留下，别把标签也塞进 JD
                ln = re.sub(r"^[^：:]{0,12}[：:]", "", ln).strip()
                if not ln:
                    continue
            elif any(w in head for w in DESC_HEADS):
                cur = desc
                if len(ln) <= 12:
                    continue
                ln = re.sub(r"^[^：:]{0,12}[：:]", "", ln).strip()
                if not ln:
                    continue
            cur.append(ln)
        out.append({"title": title, "description": "\n".join(desc)[:6000],
                    "requirements": "\n".join(req)[:6000]})
    return out


@register
class SelfHostedAdapter(Adapter):
    id = "self_hosted"

    def fetch_raw(self) -> Iterator[dict]:
        url = self.source.params.get("url")
        if not url:
            raise RuntimeError("self_hosted 源必须在 params.url 里给出招聘页地址")
        html = self.request_text("GET", url)
        for idx, blk in enumerate(parse_blocks(html)):
            blk["index"] = idx
            blk["url"] = url
            yield blk

    def normalize(self, raw: dict) -> Job:
        title = (raw.get("title") or "").strip()
        if not title:
            raise SkipRecord("标题为空")
        desc = (raw.get("description") or "").strip()
        req = (raw.get("requirements") or "").strip()
        if not desc and not req:
            # 只有标题没有正文的块，八成是页面上的栏目名——宁可丢，不写空岗
            raise SkipRecord("既无职责也无要求")
        text = f"{title} {desc[:200]}"
        rtype = str(self.source.params.get("recruit_type") or "social")
        if any(w in text for w in ("实习", "intern")):
            rtype = "intern"
        city = str(self.source.params.get("default_city") or "").strip()
        cat, sub = categorize(title)
        return Job(
            source_id=self.source.id,
            source_job_id=f"{raw.get('title')}#{raw.get('index')}",
            company=self.source.company,
            url=raw.get("url") or self.source.params.get("url"),
            title=title,
            recruit_type=rtype,
            category=cat,
            subcategory=sub,
            grad_year=grad_year_from_text(text),
            cities=[city] if city else [],
            description=desc or None,
            requirements=req or None,
        )
