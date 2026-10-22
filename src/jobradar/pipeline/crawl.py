"""编排：sources -> 适配器 -> ingest_run -> 写库。

- 同一适配器（≈同一域名，如几百个 Moka 租户）的源**串行**执行，保证对单个站点的总频率受控；
  不同适配器之间并行。
- 适配器抛出任何异常 = 该源本次失败（记日志，岗位状态不变），不影响其他源。
- SQLite 写入只在主线程进行：抓取并行，入库串行。
"""

import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from jobradar.adapters.base import Adapter, load_all, make_client
from jobradar.models import Job, SourceConfig
from jobradar.normalize import categorize, cities_from_title, grad_year_from_jd, grad_year_from_text
from jobradar.pipeline.ingest import RunResult, ingest_run, upsert_texts


def _fetch(source: SourceConfig, adapter_cls: type[Adapter], client: httpx.Client,
           sleep: Callable[[float], None]) -> tuple[list[Job] | None, str | None]:
    try:
        jobs = list(adapter_cls(source, client, sleep=sleep).fetch_all())
    except Exception as e:  # noqa: BLE001 — 任何适配器错误都只算该源失败
        return None, f"{type(e).__name__}: {e}"[:500]
    for j in jobs:
        _enrich(j)
    return jobs, None


def _enrich(j: Job) -> None:
    """适配器没给的字段，从标题中提取明写的信息（规则见 normalize.py / taxonomy/）。
    注意：cities/grad_year 计入内容哈希，修改这些提取规则会让受影响岗位产生一次 change 事件。"""
    if j.category is None and j.subcategory is None:
        j.category, j.subcategory = categorize(j.title)
    if not j.cities:
        j.cities = cities_from_title(j.title)
    if j.grad_year is None and j.recruit_type in ("campus", "intern"):
        j.grad_year = grad_year_from_text(j.title, loose=True) or grad_year_from_jd(
            j.description, j.requirements)


def _fetch_group(sources, adapter_cls, client_factory, sleep):
    client = client_factory()
    try:
        return [(s, *_fetch(s, adapter_cls, client, sleep)) for s in sources]
    finally:
        client.close()


def crawl(sources: list[SourceConfig], jobs_conn, text_conn, *, ts: str,
          client_factory: Callable[[], httpx.Client] = make_client,
          adapters: dict[str, type[Adapter]] | None = None,
          sleep: Callable[[float], None] = time.sleep,
          max_workers: int = 4) -> dict[str, RunResult]:
    adapters = adapters if adapters is not None else load_all()
    groups: dict[str, list[SourceConfig]] = defaultdict(list)
    results: dict[str, RunResult] = {}
    for s in sources:
        if not s.enabled:
            continue
        if s.adapter not in adapters:
            results[s.id] = ingest_run(jobs_conn, s.id, [], ts=ts, ok=False,
                                       error=f"unknown adapter {s.adapter}")
            continue
        groups[s.adapter].append(s)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_fetch_group, srcs, adapters[aid], client_factory, sleep)
                   for aid, srcs in groups.items()]
        for fut in as_completed(futures):
            for source, jobs, error in fut.result():
                if jobs is None:
                    results[source.id] = ingest_run(jobs_conn, source.id, [], ts=ts, ok=False, error=error)
                    continue
                res = ingest_run(jobs_conn, source.id, jobs, ts=ts)
                if res.status == "ok":
                    upsert_texts(text_conn, jobs, ts=ts)
                results[source.id] = res
    return results
