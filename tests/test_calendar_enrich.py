"""日历补全解析器的离线测试（不联网）：只认页面明写的信息，不猜。"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


doc_dates = _load("doc_dates")
wechat = _load("wechat_parse")


def test_doc_dates_reads_explicit_window():
    html = """
    <html><body>
    <h1>2027届校园招聘公告</h1>
    <p>网申时间：2026年9月1日—2026年10月31日</p>
    <p>笔试时间另行通知。</p>
    </body></html>
    """
    got = doc_dates.parse(html)
    assert got["grad_year"] == 2027
    assert (got["apply_start"], got["apply_end"]) == ("2026-09-01", "2026-10-31")


def test_doc_dates_ignores_copyright_and_same_year_noise():
    html = "<html><body><p>© 2020-2026 某某公司 版权所有</p><p>成立于 2001 年 3 月 1 日 - 2001 年 5 月 1 日</p></body></html>"
    assert doc_dates.parse(html) == {}


def test_doc_dates_rejects_absurd_window():
    """跨度超过 400 天的不算网申窗口（多半是活动周期/版权区间）。"""
    html = "<p>网申时间：2025年1月1日—2026年12月31日</p>"
    assert "apply_start" not in doc_dates.parse(html)


def test_wechat_parse_extracts_title_year_and_window():
    html = """
    <html><body>
    <h1 id="activity-name">2027届校园招聘正式启动</h1>
    <em id="publish_time">2026-09-04</em>
    <div id="js_content"><p>网申时间：2026年9月1日至10月31日，工作地点：北京、上海、深圳</p></div>
    <script>var publish_time = "2026-09-04";</script>
    </body></html>
    """
    got = wechat.parse(html)
    assert got["publish_date"] == "2026-09-04"
    assert got["grad_year"] == 2027
    assert (got["apply_start"], got["apply_end"]) == ("2026-09-01", "2026-10-31")
    assert "北京" in got["cities"]
