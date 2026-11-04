"""只读输出相同租户与跨源岗位重合候选，不合并雇主或修改来源、岗位状态。"""

import argparse
import csv
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobradar.core import queries as q  # noqa: E402
from jobradar.source_catalog import build_catalog, duplicate_enabled_tenants  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402


def write_csv(path, pairs):
    fields = ["adapter", "source_a", "source_b", "companies_a", "companies_b", "overlap",
              "records_a", "records_b", "ratio_a", "ratio_b", "same_configured_tenant",
              "classification", "sample_job_ids"]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for pair in pairs:
            row = {}
            for field in fields:
                value = pair[field]
                value = json.dumps(value, ensure_ascii=False) if isinstance(value, list) else str(value)
                row[field] = "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
            writer.writerow(row)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--sources", type=Path, default=ROOT / "sources")
    parser.add_argument("--minimum-overlap", type=int, default=3)
    parser.add_argument("--minimum-ratio", type=float, default=.9)
    parser.add_argument("--csv", type=Path)
    args = parser.parse_args(argv)
    try:
        sources = load_sources(args.sources)
        with closing(sqlite3.connect(args.db.resolve().as_uri()+"?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            result = q.source_record_overlaps(conn, build_catalog(sources),
                       minimum_overlap=args.minimum_overlap, minimum_ratio=args.minimum_ratio)
        result["duplicate_enabled_tenants"] = duplicate_enabled_tenants(sources)
        if args.csv:
            write_csv(args.csv, result["pairs"])
    except (OSError, ValueError, sqlite3.DatabaseError) as error:
        parser.exit(1, f"无法完成来源重合检查（{type(error).__name__}），请检查数据路径、配置和阈值\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(bool(result["duplicate_enabled_tenants"]))


if __name__ == "__main__":
    sys.exit(main())
