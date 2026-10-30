"""把原始侦察 JSONL 导出为报表可独立使用的最小入口证据。

只保留公司、首条已记录 URL 和原始检查时间；不重新确认入口，不发网络请求。
"""

import argparse
import json
import os
import tempfile
from pathlib import Path

import yaml
from coverage_report import ROOT, validate_careers


def export_evidence(source: Path, output: Path) -> int:
    entries = {}
    for number, line in enumerate(source.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"{source.name}:{number}: invalid JSON") from exc
        if not isinstance(row, dict) or not isinstance(row.get("best") or {}, dict):
            raise ValueError(f"{source.name}:{number}: expected an object with a best entry")
        company = row.get("company")
        url = (row.get("best") or {}).get("url")
        if not company or not url:
            continue
        if not isinstance(company, str):
            raise ValueError(f"{source.name}:{number}: company must be a string")
        # 沿用旧报表 setdefault 的首条优先规则，不能在迁移时悄悄换入口或检查日期。
        entries.setdefault(company, {"company": company, "url": url, "checked_at": row.get("at")})
    payload = {"schema_version": 1, "entries": [entries[name] for name in sorted(entries)]}
    validate_careers(payload)
    text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=120)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=output.parent,
            prefix=f".{output.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return len(entries)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "work/careers_confirmed.jsonl")
    parser.add_argument("--output", type=Path, default=ROOT / "targets/coverage_evidence.yaml")
    args = parser.parse_args()
    try:
        count = export_evidence(args.input, args.output)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        parser.exit(1, f"coverage evidence export failed: {exc}\n")
    print(f"Exported {count} entries to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
