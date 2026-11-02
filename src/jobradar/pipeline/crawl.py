"""编排：sources -> 适配器 -> ingest_run -> 写库。

- 同一适配器（≈同一域名，如几百个 Moka 租户）的源**串行**执行，保证对单个站点的总频率受控；
  不同适配器之间并行。
- 适配器抛出任何异常 = 该源本次失败（记日志，岗位状态不变），不影响其他源。
- SQLite 写入只在主线程进行：抓取并行，入库串行。
"""

import random
import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from datetime import datetime

import httpx

from jobradar.adapters.base import Adapter, CrawlBudgetExceeded, load_all, make_client
from jobradar.core import queries as q
from jobradar.models import Job, SourceConfig
from jobradar.normalize import (
    categorize,
    cities_from_title,
    degree_min_from_jd,
    normalize_cities,
    normalize_degree,
)
from jobradar.pipeline.ingest import RunResult, ingest_run, upsert_texts


def _fetch(source: SourceConfig, adapter_cls: type[Adapter], client: httpx.Client,
           sleep: Callable[[float], None], *, deadline: float | None = None, cached_texts=None
           ) -> tuple[list[Job] | None, str | None, float]:
    """返回 (岗位, 错误, 耗时秒)。耗时记进 source_run.duration_s，抓得慢的源要能被看见。"""
    started = time.monotonic()
    try:
        adapter = adapter_cls(source, client, sleep=sleep)
        adapter._crawl_deadline = deadline
        adapter.cached_texts = cached_texts or {}
        jobs = list(adapter.fetch_all())
    except CrawlBudgetExceeded:
        return None, "crawl budget exceeded", time.monotonic() - started
    except httpx.HTTPError as e:
        # HTTP异常文本可能带匿名会话查询值；只保留可诊断的状态与无查询参数的入口。
        try:
            address = str(e.request.url.copy_with(query=None))
        except RuntimeError:
            address = ""
        status = f"HTTP {e.response.status_code}" if isinstance(e, httpx.HTTPStatusError) else ""
        return None, f"{type(e).__name__}: {status} {address}"[:500], time.monotonic() - started
    except Exception as e:  # noqa: BLE001 — 任何适配器错误都只算该源失败
        return None, f"{type(e).__name__}: {e}"[:500], time.monotonic() - started
    for j in jobs:
        _enrich(j)
    return jobs, None, time.monotonic() - started


def _enrich(j: Job) -> None:
    """适配器没给的字段，从标题中提取明写的信息（规则见 normalize.py / taxonomy/）。
    注意：cities/grad_year 计入内容哈希，修改这些提取规则会让受影响岗位产生一次 change 事件。

    这里**不碰 grad_year**：适配器是"该站点怎么判届别"的唯一权威，它明确判定"取不到"
    时不能再用通用规则补一次。字节跳动的实测（2026-10-26）：2023 年挂到现在的实习岗，
    JD 里写着"2023届"，适配器已按发布时间把它判为不可信并留空，这里用
    grad_year_from_jd 又补回 2027 —— 于是"2027届在招"出现在一个 2023 年的岗位上。
    """
    if j.category is None and j.subcategory is None:
        j.category, j.subcategory = categorize(j.title)
    j.cities = normalize_cities(j.cities)
    if not j.cities:
        j.cities = cities_from_title(j.title)
    # 学历：平台原值先归一到四档；平台没给（或只写"不限"）时才从 JD 正文用带锚点的规则补。
    # degree_min 参与 content_hash，这一条上线后受影响的岗位会在下一轮产生一次 changed 事件，
    # 之后稳定；不补的话约三分之一的岗位永远没有学历字段。
    if j.degree_min:
        j.degree_min = normalize_degree(j.degree_min)
    elif j.description or j.requirements:
        j.degree_min = degree_min_from_jd(f"{j.description or ''}\n{j.requirements or ''}")


def _fetch_group(sources, adapter_cls, client_factory, sleep, deadline=None, source_budget=None, cached_texts=None):
    client = client_factory()
    out = []
    try:
        for s in sources:
            # 预算守卫：整轮采集有时间上限，超时就跳过剩下的源（标记为失败），
            # 正在分页的源也由基类逐次检查预算，不能只限制后续尚未开始的源。
            if deadline is not None and time.monotonic() >= deadline:
                out.append((s, None, "crawl budget exceeded", 0.0))
                continue
            source_deadline = min(deadline or float("inf"), time.monotonic() + source_budget) if source_budget else deadline
            out.append((s, *_fetch(s, adapter_cls, client, sleep, deadline=source_deadline,
                                   cached_texts=(cached_texts or {}).get(s.id))))
        return out
    finally:
        client.close()


def _expected_max(source: SourceConfig) -> int | None:
    """源设了 max_pages 时，这次抓取最多能拿到多少条（用于骤降基线，见 ingest_run.expected_max）。"""
    cap = source.max_pages
    if not cap:
        return None
    size = int(source.params.get("page_size") or 100)
    return cap * size


def _site_key(source: SourceConfig) -> str:
    """同一个站点（同 host 或同租户）的源必须串行，保证对单站点的 1 req/s。"""
    p = source.params or {}
    if source.adapter == "hotjob":
        return str(p.get("host") or "wecruit.hotjob.cn")
    return str(p.get("host") or p.get("tenant") or source.id)


def _saved_texts(sources, jobs_conn, text_conn):
    """主线程读取缓存；SQLite连接不会被交给抓取线程。"""
    result = {}
    for source in sources:
        hours = source.params.get("detail_cache_hours", 0)
        if not source.enabled or source.adapter != "hotjob" or type(hours) is not int or not 0 < hours <= 168:
            continue
        metadata = {r["id"]: dict(r) for r in jobs_conn.execute(
            "SELECT id,source_job_id,title,publish_at,recruit_type,degree_min FROM job WHERE source_id=?", (source.id,))}
        prefix = source.id + ":"
        cached = {}
        for row in text_conn.execute(
                "SELECT job_id,description,requirements,fetched_at FROM job_text WHERE job_id>=? AND job_id<?",
                (prefix, source.id + ";")):
            meta = metadata.get(row[0])
            if meta is not None:
                cached[meta["source_job_id"]] = {**meta, "description": row[1], "requirements": row[2], "fetched_at": row[3]}
        result[source.id] = cached
    return result


def crawl(sources: list[SourceConfig], jobs_conn, text_conn, *, ts: str,
          client_factory: Callable[[], httpx.Client] = make_client,
          adapters: dict[str, type[Adapter]] | None = None,
          sleep: Callable[[float], None] = time.sleep,
          max_workers: int = 4, budget_seconds: float | None = None,
          order_seed: int | None = None, source_budget: float | None = None) -> dict[str, RunResult]:
    if client_factory is make_client:
        from jobradar.compliance import RobotsPolicy

        policy = RobotsPolicy()
        client_factory = lambda: make_client(policy=policy)  # noqa: E731 — 每个站点组自己的连接，共用守卫
    adapters = adapters if adapters is not None else load_all()
    deadline = time.monotonic() + budget_seconds if budget_seconds else None
    cached_texts = _saved_texts(sources, jobs_conn, text_conn)
    # 并行单位从「适配器」改成「适配器 + 站点」：北森几百个租户各自是不同子域，
    # 串行跑一轮要 70+ 分钟（daily 常年贴着 90 分钟预算）；按站点分组后不同子域可以并行，
    # 同一站点（如 wecruit.hotjob.cn 上的多个租户）仍然串行，1 req/s 的承诺不变。
    groups: dict[tuple[str, str], list[SourceConfig]] = defaultdict(list)
    results: dict[str, RunResult] = {}
    for s in sources:
        if not s.enabled:
            continue
        if s.adapter not in adapters:
            results[s.id] = ingest_run(jobs_conn, s.id, [], ts=ts, ok=False,
                                       error=f"unknown adapter {s.adapter}")
            continue
        groups[(s.adapter, _site_key(s))].append(s)

    # 组顺序每天轮换一次：站点组比预算多得多，固定顺序会让排在 5,400 秒之后的源
    # 永远抢不到预算（源数从 738 涨到 1,125 之后尾部已经占三成）。用日期做种子，
    # 同一天内顺序稳定、跨天整体轮转，跑满 K 天每个源都会被轮到。
    items = list(groups.items())
    seed = order_seed if order_seed is not None else int(datetime.now().strftime("%Y%m%d"))
    rng = random.Random(seed)
    rng.shuffle(items)
    state = q.data_status(jobs_conn, now=ts)
    last_ok = {r["source_id"]: r["last_ok"] for r in state if r["last_ok"]}
    workloads = {r["source_id"]: r["open_jobs"] for r in state}
    # 共用 host 的源仍串行，但也要轮换组内顺序，避免同一批尾部租户每天都被预算跳过。
    for _, srcs in items:
        rng.shuffle(srcs)
        srcs.sort(key=lambda source: (not workloads.get(source.id, 0), last_ok.get(source.id, ""),
                                     -workloads.get(source.id, 0)))
    items.sort(key=lambda item: (last_ok.get(item[1][0].id, ""),
                                 -sum(workloads.get(source.id, 0) for source in item[1])))

    observed = [item for item in items if any(workloads.get(s.id, 0) for s in item[1])]
    discovery = [item for item in items if not any(workloads.get(s.id, 0) for s in item[1])]
    with ExitStack() as stack:
        # 未验证源可能持续等到单源预算，不能把全部线程占满、让十万条已有岗位失去刷新机会。
        # 保留独立探索容量；同站点仍在同一个串行组中，所有客户端共用访问守卫与origin限速。
        if observed and discovery and max_workers > 1:
            discovery_workers = max(1, max_workers // 5)
            lanes = [(observed, max_workers - discovery_workers), (discovery, discovery_workers)]
        else:
            lanes = [(items, max_workers)]
        futures = []
        for groups_in_lane, workers in lanes:
            pool = stack.enter_context(ThreadPoolExecutor(max_workers=workers))
            futures.extend(pool.submit(_fetch_group, srcs, adapters[aid], client_factory, sleep, deadline, source_budget, cached_texts)
                           for (aid, _site), srcs in groups_in_lane)
        for fut in as_completed(futures):
            for source, jobs, error, elapsed in fut.result():
                if jobs is None:
                    results[source.id] = ingest_run(jobs_conn, source.id, [], ts=ts, ok=False,
                                                    error=error, duration_s=elapsed)
                    continue
                res = ingest_run(jobs_conn, source.id, jobs, ts=ts,
                                 expected_max=_expected_max(source),
                                 allow_empty=bool(source.params.get("allow_empty")),
                                 duration_s=elapsed)
                if res.status == "ok":
                    upsert_texts(text_conn, jobs, ts=ts)
                results[source.id] = res
    return results
