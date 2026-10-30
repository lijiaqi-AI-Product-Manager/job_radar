"""只读牛客公开招聘日程，输出公司/时间/城市/原链接；不转载 JD、社区长文或个人资料。"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import make_client  # noqa: E402
from jobradar.discovery import NOWCODER_SCHEDULE, parse_nowcoder_schedule  # noqa: E402
from jobradar.timeutil import now_ts  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="离线回放 HTML；不将解析时间冒充在线核查时间")
    parser.add_argument("--out", type=Path, default=ROOT / ".tmp/nowcoder-leads.json")
    args = parser.parse_args()
    if args.input:
        html = args.input.read_text(encoding="utf-8")
        checked_at = None
    else:
        with make_client() as client:
            response = client.get(NOWCODER_SCHEDULE)
            response.raise_for_status()
            html = response.text
        checked_at = now_ts()
    result = parse_nowcoder_schedule(html)
    result["retrieved_at"] = checked_at
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Discovered {len(result['leads'])} link leads; page={result['current_page']}; no verified coverage asserted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
