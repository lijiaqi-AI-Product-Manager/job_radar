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
from datetime import datetime

import httpx

from jobradar.adapters.base import Adapter, load_all, make_client
from jobradar.models import Job, SourceConfig
from jobradar.normalize import (
    categorize,
    cities_from_title,
    degree_min_from_jd,
    normalize_degree,
)
from jobradar.pipeline.ingest import RunResult, ingest_run, upsert_texts


def _fetch(source: SourceConfig, adapter_cls: type[Adapter], client: httpx.Client,
           sleep: Callable[[float], None]) -> tuple[list[Job] | None, str | None, float]:
    """返回 (岗位, 错误, 耗时秒)。耗时记进 source_run.duration_s，抓得慢的源要能被看见。"""
    started = time.monotonic()
    try:
        jobs = list(adapter_cls(source, client, sleep=sleep).fetch_all())
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
    if not j.cities:
        j.cities = cities_from_title(j.title)
    # 学历：平台原值先归一到四档；平台没给（或只写"不限"）时才从 JD 正文用带锚点的规则补。
    # degree_min 参与 content_hash，这一条上线后受影响的岗位会在下一轮产生一次 changed 事件，
    # 之后稳定；不补的话约三分之一的岗位永远没有学历字段。
    if j.degree_min:
        j.degree_min = normalize_degree(j.degree_min)
    elif j.description or j.requirements:
        j.degree_min = degree_min_from_jd(f"{j.description or ''}\n{j.requirements or ''}")


def _fetch_group(sources, adapter_cls, client_factory, sleep, deadline=None):
    client = client_factory()
    out = []
    try:
        for s in sources:
            # 预算守卫：整轮采集有时间上限，超时就跳过剩下的源（标记为失败），
            # 保证 daily 不会因为某个超慢的站点拖到 workflow 120 分钟上限而整体失败。
            if deadline is not None and time.monotonic() > deadline:
                out.append((s, None, "crawl budget exceeded", 0.0))
                continue
            out.append((s, *_fetch(s, adapter_cls, client, sleep)))
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
    return str(p.get("host") or p.get("tenant") or source.id)


def crawl(sources: list[SourceConfig], jobs_conn, text_conn, *, ts: str,
          client_factory: Callable[[], httpx.Client] = make_client,
          adapters: dict[str, type[Adapter]] | None = None,
          sleep: Callable[[float], None] = time.sleep,
          max_workers: int = 4, budget_seconds: float | None = None,
          order_seed: int | None = None) -> dict[str, RunResult]:
    adapters = adapters if adapters is not None else load_all()
    deadline = time.monotonic() + budget_seconds if budget_seconds else None
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
    random.Random(seed).shuffle(items)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_fetch_group, srcs, adapters[aid], client_factory, sleep, deadline)
                   for (aid, _site), srcs in items]
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
