"""诊断腾讯校招详情接口：逐岗位请求详情（1 req/s，与每日采集相同的请求量），统计返回状态与 JD 是否为空。

用法：python scripts/diag_tencent_campus.py [--max-pages N]
"""

import argparse
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters import tencent_campus as tc  # noqa: E402
from jobradar.adapters.base import SkipRecord, make_client  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402


class Probe(tc.TencentCampusAdapter):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.log = []

    def request_json(self, method, url, **kw):
        d = super().request_json(method, url, **kw)
        if url == tc.DETAIL_URL:
            data = d.get("data") or {}
            self.log.append((d.get("status"), d.get("message"), bool(data.get("desc")), bool(data.get("request")),
                             sorted(data)[:12] if isinstance(data, dict) else type(data).__name__))
        return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int)
    args = ap.parse_args()
    src = next(s for s in load_sources(ROOT / "sources") if s.id == "tencent-campus")
    if args.max_pages:
        src.params["max_pages"] = args.max_pages
    a = Probe(src, make_client())
    raws = list(a.fetch_raw())
    print(f"list items: {len(raws)}  unique postId: {len({r.get('postId') for r in raws})}")
    print("project:", collections.Counter(r.get("projectName") for r in raws).most_common(10))
    print("detail (status, message, has_desc, has_req):",
          collections.Counter(x[:4] for x in a.log).most_common(10))
    for i in range(0, len(a.log), 100):
        chunk = a.log[i:i + 100]
        print(f"  #{i:4d}-{i + len(chunk) - 1:4d}: desc {sum(x[2] for x in chunk):3d}/{len(chunk)}  "
              f"status {dict(collections.Counter(x[0] for x in chunk))}")
    empty = [(r.get("postId"), r.get("projectName"), x) for r, x in zip(raws, a.log, strict=False) if not x[2]][:8]
    for e in empty:
        print("  empty:", e)
    jobs = []
    for r in raws:
        try:
            jobs.append(a.normalize(r))
        except SkipRecord:
            pass
    print(f"normalized: {len(jobs)}  with description: {sum(bool(j.description) for j in jobs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
