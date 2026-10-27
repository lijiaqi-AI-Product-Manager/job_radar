"""`self_hosted` 适配器：单页手写 HTML 招聘页。

覆盖两类真实页面（都是 2026-10-27 实测）：
  - Keep `www.calorietech.com/join`：`<div class="jd"><h3>岗位</h3><p>「职责…」</p><ol>…</ol></div>`，
    职责/要求用「「职责：希望由你来做」」「「要求：我们需要的你」」分段；
  - 华通集团 `www.ht-hvaton.cn/join-us/`：`<dd><h3>岗位</h3>…<div><p>任职要求：xxx</p></div></dd>`，
    只有要求段、没有职责段，段落标记带冒号。
"""

from pathlib import Path

import httpx
import yaml

from jobradar.adapters.base import SkipRecord
from jobradar.adapters.recording import ReplayTransport
from jobradar.adapters.self_hosted import SelfHostedAdapter, parse_blocks
from jobradar.models import SourceConfig

FX = Path(__file__).parent.parent / "fixtures" / "self_hosted"


def _source(**params) -> SourceConfig:
    data = yaml.safe_load((FX / "source.yaml").read_text(encoding="utf-8"))
    data["params"] = {**data.get("params", {}), **params}
    return SourceConfig(**data)


# ---- 回放真实响应 ----


def test_replay_real_page():
    with httpx.Client(transport=ReplayTransport(FX), timeout=5.0) as c:
        jobs = list(SelfHostedAdapter(_source(), c, sleep=lambda s: None).fetch_all())
    # Keep 页面把同一批岗位渲染了两遍（PC/移动各一套 DOM），适配器按标题去重后应为 9 条
    assert len(jobs) == 9
    assert len({j.title for j in jobs}) == 9
    titles = {j.title for j in jobs}
    assert "运维工程师" in titles
    assert "产品经理" in titles


def test_replay_splits_description_and_requirements():
    with httpx.Client(transport=ReplayTransport(FX), timeout=5.0) as c:
        jobs = list(SelfHostedAdapter(_source(), c, sleep=lambda s: None).fetch_all())
    by = {j.title: j for j in jobs}
    ops = by["运维工程师"]
    # 职责段来自「「职责：希望由你来做」」之后，要求段来自「「要求：我们需要的你」」之后
    assert ops.description and "运维" in ops.description
    assert ops.requirements and "Linux" in ops.requirements
    assert "希望由你来做" not in (ops.description or "")


def test_replay_jd_coverage():
    with httpx.Client(transport=ReplayTransport(FX), timeout=5.0) as c:
        jobs = list(SelfHostedAdapter(_source(), c, sleep=lambda s: None).fetch_all())
    assert all((j.description or "") or (j.requirements or "") for j in jobs)


# ---- 解析规则（用最小 HTML 片段，不依赖网络） ----


def test_parse_blocks_dedupes_and_requires_job_word():
    html = """
    <h3>公司文化</h3><p>我们很酷</p>
    <h3>前端开发工程师</h3><p>职责：写页面</p><ol><li>要求：三年经验</li></ol>
    <h3>前端开发工程师</h3><p>职责：写页面</p><ol><li>要求：三年经验</li></ol>
    """
    blocks = parse_blocks(html)
    assert [b["title"] for b in blocks] == ["前端开发工程师"]


def test_parse_blocks_keeps_colon_prefixed_requirement():
    # 华通集团那种「任职要求：xxx」一行到底、且没有职责段的写法
    html = '<h3> 系统运维工程师</h3><div><p>任职要求：计算机相关专业，英语六级。</p></div>'
    blocks = parse_blocks(html)
    assert len(blocks) == 1
    assert blocks[0]["description"] == ""
    # 标签要剥掉，JD 里只留正文
    assert blocks[0]["requirements"] == "计算机相关专业，英语六级。"


def test_normalize_skips_block_without_text():
    src = _source()
    adapter = SelfHostedAdapter(src, httpx.Client(transport=MockTransport()))
    with __import__("pytest").raises(SkipRecord):
        adapter.normalize({"title": "产品经理", "description": "", "requirements": "", "index": 0})


class MockTransport(httpx.BaseTransport):
    def handle_request(self, request):  # pragma: no cover - 本文件不发起真实请求
        return httpx.Response(200, text="")
