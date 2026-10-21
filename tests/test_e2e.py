"""端到端：真实 fixtures -> crawl -> 两个库 -> CLI 查询。验证各层之间的接口没有错位。"""

import json
from pathlib import Path

import httpx
import yaml

from jobradar import cli
from jobradar.adapters.base import load_all
from jobradar.adapters.recording import ReplayTransport
from jobradar.models import SourceConfig
from jobradar.pipeline.crawl import crawl
from jobradar.store.migrate import connect
from jobradar.timeutil import now_ts

FX = Path(__file__).parent / "fixtures"


class RoutingTransport(httpx.BaseTransport):
    """按域名把请求路由到对应适配器的 fixtures。"""

    def __init__(self):
        self.routes = {"careers.tencent.com": ReplayTransport(FX / "tencent"),
                       "fosunpharma.zhiye.com": ReplayTransport(FX / "beisen")}

    def handle_request(self, request):
        return self.routes[request.url.host].handle_request(request)


def fixture_source(name):
    return SourceConfig(**yaml.safe_load((FX / name / "source.yaml").read_text(encoding="utf-8")))


def test_crawl_then_query(tmp_path, monkeypatch, capsys):
    jobs = connect(tmp_path / "jobs.db", "jobs")
    text = connect(tmp_path / "jd_text.db", "text")
    res = crawl([fixture_source("tencent"), fixture_source("beisen")], jobs, text, ts=now_ts(),
                client_factory=lambda: httpx.Client(transport=RoutingTransport()),
                adapters=load_all(), sleep=lambda s: None)
    assert {k: v.status for k, v in res.items()} == {"tencent": "ok", "beisen-fosunpharma": "ok"}
    assert res["tencent"].opened == 5 and res["beisen-fosunpharma"].opened == 40
    jobs.close()
    text.close()

    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path))

    def run(*argv):
        cli.main(list(argv))
        return json.loads(capsys.readouterr().out)

    campus = run("search", "--company", "复星", "--type", "campus", "--grad-year", "2027", "--limit", "100")
    assert campus["data_as_of"] and len(campus["results"]) > 0
    assert all(r["recruit_type"] == "campus" for r in campus["results"])

    shown = run("show", campus["results"][0]["id"])
    assert shown["results"][0]["requirements"]

    assert run("search", "--company", "腾讯", "--city", "深圳")["results"]
    assert len(run("diff", "--days", "1", "--types", "open", "--limit", "500")["results"]) == 45
    hits = run("search", "--text", "本科", "--company", "腾讯")["results"]  # 全文检索命中腾讯详情接口补全的岗位要求
    assert hits and all(r["company"] == "腾讯" for r in hits) and any(r["match"] for r in hits)
    st = run("sources")
    assert st["failing"] == [] and {r["source_id"] for r in st["results"]} == {"tencent", "beisen-fosunpharma"}
