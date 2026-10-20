"""用真实网络录制某个源的 fixtures（每页一个响应），写到 tests/fixtures/<adapter_id>/。

用法：uv run python scripts/record_fixtures.py <source_id> [--max-pages 2]
- 只发少量请求（max_pages 限量），遵守 source 的限速。
- 录完必须人工/Claude 检查：不含 cookie/token/个人信息；体积 < 300KB；必要时裁剪 items。
- 运行后同目录会写入 source.yaml（max_pages 已固定），供契约测试使用。
"""

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import load_all, make_client  # noqa: E402
from jobradar.adapters.recording import RecordingTransport  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source_id")
    ap.add_argument("--max-pages", type=int, default=2)
    ap.add_argument("--page-size", type=int, default=20, help="适配器支持 params.page_size 时生效")
    args = ap.parse_args()

    source = next((s for s in load_sources(ROOT / "sources") if s.id == args.source_id), None)
    if source is None:
        print(f"source {args.source_id} not found in sources/")
        return 1
    source.params = {**source.params, "max_pages": args.max_pages, "page_size": args.page_size}
    out = ROOT / "tests" / "fixtures" / source.adapter
    transport = RecordingTransport(out)
    adapter = load_all(include_drafts=True)[source.adapter](source, make_client(transport))
    jobs = list(adapter.fetch_all())
    (out / "source.yaml").write_text(
        yaml.safe_dump(source.model_dump(mode="json"), allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    print(f"recorded {len(transport.entries)} responses, {len(jobs)} jobs -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
