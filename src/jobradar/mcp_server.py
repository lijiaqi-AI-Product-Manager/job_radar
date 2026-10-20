"""jobradar MCP server：只读薄壳，所有逻辑在 core/queries.py。

安装：pip install "jobradar[mcp] @ git+https://github.com/lijiaqimun-coder/job_radar"
运行：jobradar-mcp（stdio）。数据需先用 `jobradar update` 下载。
"""

from datetime import timedelta

from mcp.server.mcpserver import MCPServer

from jobradar.core import queries as q
from jobradar.local import NoData, envelope, open_db
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
                keyword: str | None = None, include_closed: bool = False, limit: int = 30) -> dict:
    """搜索在招岗位。recruit_type: campus(校招)/intern(实习)/social(社招)；company 为名称子串；
    category 匹配职类大类或子类（如 技术、算法、后端、产品）；keyword 匹配岗位标题。"""
    def run():
        conn = open_db("jobs")
        rows = q.search_jobs(conn, company=company, category=category, city=city,
                             recruit_type=recruit_type, grad_year=grad_year, keyword=keyword,
                             include_closed=include_closed, limit=min(limit, 200))
        return envelope(conn, rows)
    return _guard(run)


@server.tool()
def get_job(job_id: str) -> dict:
    """岗位详情，含 JD 原文（若已下载 JD 库）。job_id 来自 search_jobs 结果的 id。"""
    def run():
        conn = open_db("jobs")
        job = q.get_job(conn, open_db("text", required=False), job_id)
        return envelope(conn, [job] if job else [], found=job is not None)
    return _guard(run)


@server.tool()
def recent_changes(days: int = 7, company: str | None = None, types: list[str] | None = None,
                   limit: int = 200) -> dict:
    """最近 N 天的岗位变化。types 可选 open(新开)/close(下架)/change(变更)/reopen(重开)。"""
    def run():
        conn = open_db("jobs")
        since = (parse_ts(now_ts()) - timedelta(days=days)).strftime(FMT)
        rows = q.recent_changes(conn, since=since, company=company, types=types, limit=min(limit, 500))
        return envelope(conn, rows, since=since)
    return _guard(run)


@server.tool()
def compare_roles(companies: list[str], category: str | None = None, keyword: str | None = None,
                  per_company: int = 5) -> dict:
    """取多家公司同类岗位的 JD 原文，供对比要求差异。按职类 category 和/或标题关键词 keyword 选岗位（至少给一个）。
    not_found 列出数据里没有匹配岗位的公司。"""
    def run():
        conn = open_db("jobs")
        text = open_db("text", required=False)
        if text is None:
            return {"error": "对比需要 JD 原文库：运行 `jobradar update --with-text`", "results": {}}
        if not category and not keyword:
            return {"error": "需要 category 或 keyword", "results": {}}
        out = q.compare_roles(conn, text, companies, category, keyword=keyword, per_company=min(per_company, 20))
        return envelope(conn, out, category=category, keyword=keyword,
                        not_found=[c for c, v in out.items() if not v])
    return _guard(run)


@server.tool()
def company_trend(company: str, step_days: int = 7) -> dict:
    """某公司在招岗位数随时间的变化（每 step_days 天一个点）。"""
    def run():
        conn = open_db("jobs")
        return envelope(conn, q.company_trend(conn, company, until=now_ts(), step_days=step_days),
                        company=company)
    return _guard(run)


@server.tool()
def data_status() -> dict:
    """各数据源最近抓取状态与数据新鲜度。"""
    def run():
        conn = open_db("jobs")
        rows = q.data_status(conn, now=now_ts())
        return envelope(conn, rows, failing=[r["source_id"] for r in rows if r["stale"]])
    return _guard(run)


def main():
    server.run()


if __name__ == "__main__":
    main()
