"""上线前冒烟：对指定 source 真实抓一页，报告岗位数 / JD 覆盖 / 耗时 / 错误。

新增或改动数据源后，用它确认"明天的 daily 不会挂"，比直接等 Actions 快。

用法：
    uv run python scripts/smoke_sources.py alibaba netease nvidia
    uv run python scripts/smoke_sources.py --file ids.txt

说明：每个源只抓 max_pages=1（列表 1 页 + 该页岗位的详情），限速沿用源配置；
不发写操作、不落库。退出码 1 表示有源失败。
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import load_all, make_client  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream.isatty():
                stream.reconfigure(errors="replace")
            else:  # 管道/重定向：给 UTF-8，别让 GBK 控制台把输出写成乱码
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", help="source id（可多个）")
    ap.add_argument("--file", help="source id 文件，一行一个")
    args = ap.parse_args()

    ids = list(args.ids)
    if args.file:
        ids += [ln.strip() for ln in Path(args.file).read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.startswith("#")]
    if not ids:
        ap.error("至少给一个 source id")

    sources = {s.id: s for s in load_sources(ROOT / "sources")}
    adapters = load_all()
    failures = 0
    print(f"{'source':28s} {'岗':>5s} {'JD':>5s} {'秒':>6s}  结果")
    with make_client() as client:
        for sid in ids:
            src = sources.get(sid)
            if src is None:
                print(f"{sid:28s} {'-':>5s} {'-':>5s} {'-':>6s}  source 不存在")
                failures += 1
                continue
            src.params = {**src.params, "max_pages": 1}
            adapter = adapters[src.adapter](src, client, sleep=lambda s: None)
            started = time.time()
            try:
                jobs = list(adapter.fetch_all())
                with_jd = sum(1 for j in jobs if (j.description or "").strip() or (j.requirements or "").strip())
                print(f"{sid:28s} {len(jobs):5d} {with_jd:5d} {time.time() - started:6.1f}  ok")
                if jobs and with_jd < 0.9 * len(jobs):
                    print(f"    ! JD 覆盖 {with_jd}/{len(jobs)} < 90%")
            except Exception as e:  # noqa: BLE001 — 冒烟就是要把错误打出来
                failures += 1
                print(f"{sid:28s} {'-':>5s} {'-':>5s} {time.time() - started:6.1f}  "
                      f"FAIL {type(e).__name__}: {str(e)[:120]}")
    print(f"\n{len(ids) - failures}/{len(ids)} 通过", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
