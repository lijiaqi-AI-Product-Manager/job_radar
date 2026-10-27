"""公众号推文解析：日历里「网申时间」字段最可靠的公开来源。

背景（2026-10-26 实测，四条官方推文逐个验证）：
  - 旧版 `wechat_parse.py` 优先用 Playwright 渲染，**渲染出来的全是 22 KB 的
    「环境异常，完成验证后即可继续访问」壳页**（无头浏览器指纹被识别），
    四条推文解析结果全部是 None，于是日历的网申时间一直是空的；
  - 换成普通 HTTP GET 就能拿到 3.5 MB 完整文章页——但**UA 写法决定命运**：
    带联系地址的 `jobradar/0.1 (+https://github.com/...)` 被拦；
    短的 `Mozilla/5.0 (compatible; jobradar-bot/0.1)` 通过。两者都是诚实爬虫标识，
    区别只是后者不带 URL，所以不构成伪装浏览器；
  - 日期字段有四种写法（`var ct`、`var publish_time`、`id="publish_time"`、`var create_time`），
    旧版只认其中一种，加上拿不到页面，所以"看起来像是抓不到"。

这里用 fixtures 回放锁定解析结果，避免每天重新爬公众号才能发现回归。
"""

import importlib.util
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "wechat"


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "scripts" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wx = _load("wechat_parse_under_test", "wechat_parse.py")


def _html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_sinopec_post_yields_the_application_window():
    """中石化炼化工程 2027 校招：推文正文写明「2026年9月24日—10月28日」。

    这一条是「网申时间」字段的真实样本——数据层（北森/大易）不给这个日期时，
    公众号正文是唯一的公开来源。
    """
    got = wx.parse(_html("sinopec_2027.html"))
    assert got["publish_date"] == "2026-10-08"
    assert got["apply_start"] == "2026-09-24"
    assert got["apply_end"] == "2026-10-28"
    assert "中石化" in got["title"]
    assert "北京" in got["cities"]


def test_cscec_post_gives_title_and_date_even_without_a_window():
    """中建三局深圳：正文是长图，抓不到文字日期——那就只出标题+发布日期，绝不编造窗口。"""
    got = wx.parse(_html("cscec3sz_2027.html"))
    assert got["publish_date"] == "2026-09-11"
    assert got["grad_year"] == 2027
    assert "中建三局" in got["title"]
    assert got.get("apply_start") is None and got.get("apply_end") is None


@pytest.mark.parametrize("marker", ["环境异常", "完成验证后即可继续访问", "请输入验证码"])
def test_block_page_is_recognised(marker):
    """验证页必须被识别出来：否则会被当成正文，抽出"版权年份"冒充网申时间。"""
    assert wx._is_blocked(f"<html><body>{marker}</body></html>")


def test_real_article_is_not_mistaken_for_a_block_page():
    """正文页里也会出现 captcha（JS 资源名），不能因此误判成拦截页。"""
    assert not wx._is_blocked(_html("sinopec_2027.html"))


def test_plain_fetch_is_tried_before_rendering(monkeypatch):
    """顺序不能反：渲染路径对公众号返回的是验证页。用 monkeypatch 锁住调用顺序。"""
    calls: list[str] = []

    def fake_plain(url):
        calls.append("plain")
        return "x" * 6000

    def fake_render(url):
        calls.append("render")
        return "y" * 6000

    monkeypatch.setattr(wx, "_fetch_plain", fake_plain)
    monkeypatch.setattr(wx, "_fetch_render", fake_render)
    out = wx.fetch("https://mp.weixin.qq.com/s/demo")
    assert calls == ["plain"]      # 拿到了正文就不再走渲染
    assert out == "x" * 6000


def test_render_is_used_only_when_plain_is_blocked(monkeypatch):
    """普通 GET 被拦时才退回渲染——渲染对少数文章仍可能有效，但不能作为首选。"""
    calls: list[str] = []

    def fake_plain(url):
        calls.append("plain")
        return "<html><body>环境异常，完成验证后即可继续访问</body></html>"

    def fake_render(url):
        calls.append("render")
        return "<html><body>" + "正文" * 3000 + "</body></html>"

    monkeypatch.setattr(wx, "_fetch_plain", fake_plain)
    monkeypatch.setattr(wx, "_fetch_render", fake_render)
    out = wx.fetch("https://mp.weixin.qq.com/s/demo")
    assert calls == ["plain", "render"]
    assert "环境异常" not in out
