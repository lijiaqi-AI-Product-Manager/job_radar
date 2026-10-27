"""jobradar MCP server：只读薄壳，所有逻辑在 core/queries.py。

安装：pip install "jobradar[mcp] @ git+https://github.com/lijiaqimun-coder/job_radar"
运行：jobradar-mcp（stdio）。数据需先用 `jobradar update` 下载。
"""

import sqlite3
from contextlib import nullcontext
from datetime import timedelta

from mcp.server.mcpserver import MCPServer

from jobradar import __version__
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
    except sqlite3.DatabaseError as e:
        return {"error": f"本地数据读取失败（{e}）；运行 `jobradar update --force` 重新下载", "results": []}


@server.tool()
def search_jobs(company: str | None = None, category: str | None = None, city: str | None = None,
                recruit_type: str | None = None, grad_year: int | None = None,
                keyword: str | None = None, text: str | None = None,
                include_closed: bool = False, limit: int = 30,
                contains: bool = False, dedupe: bool = False,
                exclude_store: bool = False,
                deadline_before: str | None = None,
                deadline_after: str | None = None) -> dict:
    """搜索在招岗位。recruit_type: campus(校招)/intern(实习)/social(社招)；
    company 为公司名（支持「中核」这类简称映射）；匹配不上时返回空 + company_match 说明是
    「未收录」还是「命中多家」，不要据此推断该公司没在招。contains=True 才按子串匹配；
    dedupe=True 折叠「同公司+同标题+同城市」的多条 req（全库约 9.2%，结果带 variants 原条数）；
    exclude_store=True 排掉门店/零售岗（校招用户常用）。
    结果为 0 且该公司在日历里有条目时，返回里的 calendar 字段给出 `jobradar calendar --group X`，
    按它引导用户，不要说"这家公司没在招"。
    category 匹配职类大类或子类（如 技术、算法、后端、产品）；keyword 只匹配岗位标题；
    text 为全文检索（标题 + JD 职责/要求原文，空格分隔的词须全部出现，如 "PyTorch 大模型"），
    结果带 match（JD 中命中处的片段，仅标题命中时为 null）。
    deadline_before / deadline_after 为 YYYY-MM-DD，按**网申截止日**筛（"这周快截止的"用
    deadline_before=本周日）。只有源里明确写了截止日的岗位参与比较——目前约 2.6%，
    所以返回为空不等于"没有快截止的岗位"，要在回答里说明这个口径。"""
    def run():
        text_cm = db("text", required=False) if text else nullcontext(None)
        with db("jobs") as conn, text_cm as text_conn:
            if text and text_conn is None:
                return {"error": "全文检索需要 JD 原文库：先运行 `jobradar update`", "results": []}
            meta = {}
            rows = q.search_jobs(conn, company=company, category=category, city=city,
                                 recruit_type=recruit_type, grad_year=grad_year, keyword=keyword,
                                 text=text, text_conn=text_conn, include_closed=include_closed,
                                 limit=min(limit, 200), contains=contains, meta=meta,
                                 dedupe=dedupe, exclude_store=exclude_store,
                                 deadline_before=deadline_before,
                                 deadline_after=deadline_after)
            payload = envelope(conn, rows, **meta)
            hints = q.empty_result_hints(rows, company_match=meta.get("company_match"),
                                         grad_year=grad_year, city=city, category=category)
            if not rows and company:
                with db("calendar", required=False) as cal:
                    if cal is not None and (ch := q.calendar_hint(cal, company)):
                        payload["calendar"] = ch
                        hints = [h for h in hints if "公司名没有唯一确定" not in h]
                        hints.append(f"岗位数据里没有，但日历里有 {ch['entries']} 条"
                                     f"（届次：{'、'.join(map(str, ch['grad_years'])) or '未标注'}；"
                                     f"批次：{'、'.join(ch['project_types']) or '未标注'}）")
                        if ch.get("apply_url"):
                            hints.append(f"投递入口：{ch['apply_url']}")
                        if ch.get("hint"):
                            hints.append(ch["hint"])
            if hints:
                payload["hints"] = hints
            return payload
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
                   limit: int = 200, contains: bool = False) -> dict:
    """最近 N 天的岗位变化。types 可选 open(新开)/close(下架)/change(变更)/reopen(重开)。"""
    def run():
        with db("jobs") as conn:
            since = (parse_ts(now_ts()) - timedelta(days=days)).strftime(FMT)
            meta = {}
            rows = q.recent_changes(conn, since=since, company=company, types=types,
                                    limit=min(limit, 500), contains=contains, meta=meta)
            return envelope(conn, rows, since=since, **meta)
    return _guard(run)


@server.tool()
def new_jobs_by_category(days: int = 7, limit: int = 10, company: str | None = None,
                         contains: bool = False) -> dict:
    """最近 N 天新开的岗位按职类统计（没有职类的归到「未分类」），按数量降序。
    company 可选：只统计这家公司。回答「最近哪类职位新增最多」用它，不要自己比对两次 search 结果。"""
    def run():
        with db("jobs") as conn:
            since = (parse_ts(now_ts()) - timedelta(days=days)).strftime(FMT)
            meta = {}
            rows = q.new_jobs_by_category(conn, since=since, limit=min(limit, 50),
                                          company=company, contains=contains, meta=meta)
            return envelope(conn, rows, since=since, **meta)
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
def company_trend(company: str, step_days: int = 7, contains: bool = False) -> dict:
    """某公司在招岗位数随时间的变化（每 step_days 天一个点）。"""
    def run():
        with db("jobs") as conn:
            meta = {}
            rows = q.company_trend(conn, company, until=now_ts(), step_days=step_days,
                                   contains=contains, meta=meta)
            return envelope(conn, rows, company=company, **meta)
    return _guard(run)


@server.tool()
def data_status(verbose: bool = False) -> dict:
    """各数据源最近抓取状态与数据新鲜度。默认返回计数 + 有问题的源（整表 277 行约 15k tokens，
    多数情况下你只需要知道"有没有源坏了"）；需要逐源明细时传 verbose=True。"""
    def run():
        with db("jobs") as conn:
            rows = q.data_status(conn, now=now_ts())
            failing = [r["source_id"] for r in rows if r["stale"]]
            if verbose:
                return envelope(conn, rows, failing=failing)
            return envelope(conn, [], failing=failing, **q.data_status_summary(rows))
    return _guard(run)


@server.tool()
def calendar(group: str | None = None, company: str | None = None, project_type: str | None = None,
             grad_year: int | None = None, origin: str | None = None, open_on: str | None = None,
             city: str | None = None, direction: str | None = None,
             deadline_before: str | None = None, deadline_after: str | None = None,
             has_tracks: bool = False, has_window: bool = False,
             limit: int = 50) -> dict:
    """招聘日历：各公司的招聘项目（提前批/秋招正式批/暑期实习/社招…）、届次、方向、网申时间、城市、投递入口与来源。
    覆盖抓不到 JD 的大厂（人工从官方公众号/官网/政府平台整理，origin=manual），以及数据层自动生成的条目（origin=auto）。
    group 集团（如 阿里巴巴）、company 具体公司或产品（如 飞猪）、project_type 子串匹配（如 秋招、实习）；
    open_on=YYYY-MM-DD 只看当天网申开放中的；jd_status=linked 表示可用 search_jobs 查到 JD；
    jd_status=blocked 时把 hint 原样放在回答末尾。

    按城市/方向/截止日筛（回答「我能在北京投什么」「11 月前截止的还有哪些」用这几个参数）：
    city（如 北京）、direction（方向名子串，如 算法 / 技术类）、deadline_before / deadline_after（YYYY-MM-DD）。
    has_tracks=True 只返回有方向的条目，has_window=True 只返回有网申时间的条目（起止**任一**有值即可，
    只有截止日的也算——那正是「什么时候之前必须投」）。

    重要口径：只有部分条目写了城市和截止日（校招/实习口径：城市约 45%、网申时间约 20%），
    所以「city=某地 返回空」不等于「该地没有岗位」，回答时要说明这一点，不能让用户以为没机会。
    另外条目里 project_type=社招 的那些是社招板岗位，没有届次也没有批次窗口，别当校招批次讲。"""
    def run():
        with db("calendar") as conn:
            rows = q.calendar_entries(conn, group=group, company=company, project_type=project_type,
                                      grad_year=grad_year, origin=origin, open_on=open_on,
                                      city=city, direction=direction,
                                      deadline_before=deadline_before, deadline_after=deadline_after,
                                      has_tracks=True if has_tracks else None,
                                      has_window=True if has_window else None,
                                      limit=min(limit, 200))
            env = envelope(None, rows, as_of=q.calendar_as_of(conn))
            # 空结果不能只说「没有」：把「是因为筛选太窄还是真的没有」讲清楚
            if not rows and (city or direction):
                env["advice"] = q.calendar_filter_advice(conn, city=city, direction=direction)
            return env
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

    _ver = __version__

    ap = argparse.ArgumentParser(
        prog="jobradar-mcp",
        description="job_radar MCP server (stdio). Put this command in your MCP client config; no arguments needed.",
    )
    ap.add_argument("--version", action="version", version=f"jobradar-mcp {_ver}")
    ap.parse_args(argv)
    server.run()


if __name__ == "__main__":
    main()
