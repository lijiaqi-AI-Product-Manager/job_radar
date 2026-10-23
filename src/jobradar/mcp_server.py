"""jobradar MCP server：只读薄壳，所有逻辑在 core/queries.py。

安装：pip install "jobradar[mcp] @ git+https://github.com/lijiaqimun-coder/job_radar"
运行：jobradar-mcp（stdio）。数据需先用 `jobradar update` 下载。
"""

from contextlib import nullcontext
from datetime import timedelta

from mcp.server.mcpserver import MCPServer

from jobradar.core import queries as q
from jobradar.local import NoData, db, envelope
from jobradar.timeutil import FMT, now_ts, parse_ts

INSTRUCTIONS = """中国公司在招岗位数据（校招/实习/社招），来自各公司官方招聘页，每日更新。
回答时：注明 data_as_of；每个岗位附 url；只用返回的数据，不编造；results 为空说明"数据里没有"，
而不是"该公司没在招"；stale 为 true 时提醒用户运行 `jobradar update`。"""

server = MCPServer("jobradar", instructions=INSTRUCTIONS)


def _guard(fn):
    try:
        return fn()
    except NoData as e:
        return {"error": str(e), "results": []}


@server.tool()
def search_jobs(company: str | None = None, category: str | None = None, city: str | None = None,
                recruit_type: str | None = None, grad_year: int | None = None,
                keyword: str | None = None, text: str | None = None,
                include_closed: bool = False, limit: int = 30) -> dict:
    """搜索在招岗位。recruit_type: campus(校招)/intern(实习)/social(社招)；company 为名称子串；
    category 匹配职类大类或子类（如 技术、算法、后端、产品）；keyword 只匹配岗位标题；
    text 为全文检索（标题 + JD 职责/要求原文，空格分隔的词须全部出现，如 "PyTorch 大模型"），
    结果带 match（JD 中命中处的片段，仅标题命中时为 null）。"""
    def run():
        text_cm = db("text", required=False) if text else nullcontext(None)
        with db("jobs") as conn, text_cm as text_conn:
            if text and text_conn is None:
                return {"error": "全文检索需要 JD 原文库：先运行 `jobradar update`", "results": []}
            rows = q.search_jobs(conn, company=company, category=category, city=city,
                                 recruit_type=recruit_type, grad_year=grad_year, keyword=keyword,
                                 text=text, text_conn=text_conn, include_closed=include_closed,
                                 limit=min(limit, 200))
            return envelope(conn, rows)
    return _guard(run)


@server.tool()
def get_job(job_id: str) -> dict:
    """岗位详情，含 JD 原文（若已下载 JD 库）。job_id 来自 search_jobs 结果的 id。"""
    def run():
        with db("jobs") as conn, db("text", required=False) as text_conn:
            job = q.get_job(conn, text_conn, job_id)
            return envelope(conn, [job] if job else [], found=job is not None)
    return _guard(run)


@server.tool()
def recent_changes(days: int = 7, company: str | None = None, types: list[str] | None = None,
                   limit: int = 200) -> dict:
    """最近 N 天的岗位变化。types 可选 open(新开)/close(下架)/change(变更)/reopen(重开)。"""
    def run():
        with db("jobs") as conn:
            since = (parse_ts(now_ts()) - timedelta(days=days)).strftime(FMT)
            rows = q.recent_changes(conn, since=since, company=company, types=types, limit=min(limit, 500))
            return envelope(conn, rows, since=since)
    return _guard(run)


@server.tool()
def new_jobs_by_category(days: int = 7, limit: int = 10) -> dict:
    """最近 N 天新开的岗位按职类统计（没有职类的归到「未分类」），按数量降序。
    回答「最近哪类职位新增最多」用它，不要自己比对两次 search 结果。"""
    def run():
        with db("jobs") as conn:
            since = (parse_ts(now_ts()) - timedelta(days=days)).strftime(FMT)
            rows = q.new_jobs_by_category(conn, since=since, limit=min(limit, 50))
            return envelope(conn, rows, since=since)
    return _guard(run)


@server.tool()
def compare_roles(companies: list[str], category: str | None = None, keyword: str | None = None,
                  text: str | None = None, per_company: int = 5) -> dict:
    """取多家公司同类岗位的 JD 原文，供对比要求差异。按职类 category、标题关键词 keyword
    或 JD 全文 text 选岗位（至少给一个）。not_found 列出数据里没有匹配岗位的公司。"""
    def run():
        with db("jobs") as conn, db("text", required=False) as text_conn:
            if text_conn is None:
                return {"error": "对比需要 JD 原文库：运行 `jobradar update`", "results": {}}
            if not category and not keyword and not text:
                return {"error": "需要 category、keyword 或 text", "results": {}}
            out = q.compare_roles(conn, text_conn, companies, category, keyword=keyword, text=text,
                                  per_company=min(per_company, 20))
            return envelope(conn, out, category=category, keyword=keyword, text=text,
                            not_found=[c for c, v in out.items() if not v])
    return _guard(run)


@server.tool()
def company_trend(company: str, step_days: int = 7) -> dict:
    """某公司在招岗位数随时间的变化（每 step_days 天一个点）。"""
    def run():
        with db("jobs") as conn:
            return envelope(conn, q.company_trend(conn, company, until=now_ts(), step_days=step_days),
                            company=company)
    return _guard(run)


@server.tool()
def data_status() -> dict:
    """各数据源最近抓取状态与数据新鲜度。"""
    def run():
        with db("jobs") as conn:
            rows = q.data_status(conn, now=now_ts())
            return envelope(conn, rows, failing=[r["source_id"] for r in rows if r["stale"]])
    return _guard(run)


@server.tool()
def calendar(group: str | None = None, company: str | None = None, project_type: str | None = None,
             grad_year: int | None = None, origin: str | None = None, open_on: str | None = None,
             limit: int = 50) -> dict:
    """招聘日历：各公司的招聘项目（提前批/秋招正式批/暑期实习/社招…）、届次、方向、网申时间、城市、投递入口与来源。
    覆盖抓不到 JD 的大厂（人工从官方公众号/官网/政府平台整理，origin=manual），以及数据层自动生成的条目（origin=auto）。
    group 集团（如 阿里巴巴）、company 具体公司或产品（如 飞猪）、project_type 子串匹配（如 秋招、实习）；
    open_on=YYYY-MM-DD 只看当天网申开放中的。jd_status=linked 表示可用 search_jobs 查到 JD；
    jd_status=blocked 时把 hint 原样放在回答末尾。"""
    def run():
        with db("calendar") as conn:
            rows = q.calendar_entries(conn, group=group, company=company, project_type=project_type,
                                      grad_year=grad_year, origin=origin, open_on=open_on, limit=min(limit, 200))
            return envelope(None, rows, as_of=q.calendar_as_of(conn))
    return _guard(run)


@server.tool()
def stats() -> dict:
    """覆盖率：目标公司（500 家）中有招聘日历的、有 JD 的，按行业分布；岗位、JD 正文数量与字段覆盖率（jobs.fields）。"""
    def run():
        out = {}
        with db("calendar", required=False) as cal_conn, db("jobs", required=False) as jobs_conn, \
                db("text", required=False) as text_conn:
            if cal_conn is not None:
                out["calendar"] = q.calendar_stats(cal_conn)
                out["calendar_as_of"] = q.calendar_as_of(cal_conn)
            if jobs_conn is not None:
                out["jobs"] = q.data_summary(jobs_conn, text_conn)
        if not out:
            raise NoData("本地没有数据：先运行 `jobradar update`。")
        return out
    return _guard(run)


def main(argv: list[str] | None = None):
    """MCP stdio 服务器。默认无参数直接跑；`--help/--version` 给出说明，避免用户一脸茫然。"""
    import argparse
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _v

    try:
        _ver = _v("jobradar")
    except PackageNotFoundError:  # 直接从源码跑时没有安装元数据
        _ver = "unknown"

    ap = argparse.ArgumentParser(
        prog="jobradar-mcp",
        description="job_radar MCP server (stdio). Put this command in your MCP client config; no arguments needed.",
    )
    ap.add_argument("--version", action="version", version=f"jobradar-mcp {_ver}")
    ap.parse_args(argv)
    server.run()


if __name__ == "__main__":
    main()
