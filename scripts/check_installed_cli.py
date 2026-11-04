"""用临时离线样本验证目标环境的已安装包，避免源码路径掩盖安装问题。"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = r'''
import importlib.metadata as metadata
import json, os, sys
from datetime import timedelta
from pathlib import Path
import jobradar
from jobradar.models import Job
from jobradar.pipeline.ingest import ingest_run
from jobradar.store.migrate import connect
from jobradar.timeutil import now_ts, parse_ts, shanghai_date
from jobradar.source_catalog import catalog
from jobradar.normalize import categorize

assert Path(jobradar.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()), "import came from source tree"
home = Path(os.environ["JOBRADAR_HOME"])
ts = now_ts()
today = parse_ts(ts)
end = shanghai_date((today + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"))
expired = shanghai_date((today - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))
jobs = connect(home / "jobs.db", "jobs")
ingest_run(jobs, "smoke", [
    Job(source_id="smoke", source_job_id=str(n), company="中国核工业集团", title="离线校招样本",
        url="https://example.invalid/job", recruit_type="campus", apply_end=deadline,
        category="职能", subcategory="财务审计", cities=["苏州"])
    for n, deadline in ((1, end), (2, None))
], ts=ts)
ingest_run(jobs,"other",[Job(source_id="other",source_job_id="1",company="离线另一主体",
    title="财务经理",url="https://example.invalid/other",recruit_type="social",category="财务",cities=["北京"])],ts=ts)
ingest_run(jobs,"store",[Job(source_id="store",source_job_id="1",company="离线门店品牌",
    title="门店实习生",url="https://example.invalid/store",recruit_type="intern")],ts=ts)
jobs.close()
cal = connect(home / "calendar.db", "calendar")
for eid, city, deadline in (("beijing-open", "北京", end), ("shanghai-open", "上海", end),
                            ("beijing-ended", "北京", expired)):
    cal.execute("INSERT INTO entry(id,origin,group_name,project_type,cities,apply_end,source_type,"
                "source_name,as_of,jd_status) VALUES (?, 'manual', '离线样本', '校招', ?, ?,"
                "'official_site', '离线样本', ?, 'none')", (eid, json.dumps([city]), deadline, ts[:10]))
cal.commit()
cal.close()
direct = metadata.distribution("jobsearchradar").read_text("direct_url.json")
print(json.dumps({"version": jobradar.__version__, "module": jobradar.__file__, "deadline": end,
                  "direct_url": json.loads(direct) if direct else None,
                  "catalog_entries":len(catalog()),
                  "finance_category":categorize("财务会计"),
                  "catalog_kinds":sorted({r['source_kind'] for r in catalog().values()})}))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--workdir", type=Path, default=ROOT / ".tmp")
    parser.add_argument("--require-pinned-source", action="store_true")
    args = parser.parse_args()
    target = json.loads((ROOT / "docs/install-target.json").read_text(encoding="utf-8"))
    python = args.python.absolute()
    cli = python.with_name("jobradar.exe" if os.name == "nt" else "jobradar")
    mcp = python.with_name("jobradar-mcp.exe" if os.name == "nt" else "jobradar-mcp")
    env = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    env["PYTHONUTF8"] = "1"
    args.workdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="jobradar-install-", dir=args.workdir.resolve()) as directory:
        env["JOBRADAR_HOME"] = directory

        def run(command):
            result = subprocess.run([str(p) for p in command], cwd=directory, env=env,
                                    capture_output=True, text=True, encoding="utf-8", timeout=60)
            if result.returncode:
                raise RuntimeError(f"{command[:3]}: exit {result.returncode}\n{result.stderr[-2500:]}")
            return result.stdout

        info = json.loads(run([python, "-I", "-c", BOOTSTRAP]))
        if info["version"] != target["version"]:
            raise RuntimeError(f"installed {info['version']} != expected {target['version']}")
        if args.require_pinned_source:
            url = f"https://github.com/{target['repository']}/archive/{target['revision']}.zip"
            if (info["direct_url"] or {}).get("url") != url:
                raise RuntimeError("installed source does not match docs/install-target.json")
        checks = []

        def check(name, condition):
            if not condition:
                raise RuntimeError(f"compatibility check failed: {name}")
            checks.append(name)

        help_text = run([cli, "search", "--help"])
        check("search-help", "--deadline-before" in help_text)
        help_text = run([cli, "calendar", "--help"])
        check("calendar-help", "--city" in help_text and "--include-expired" in help_text)
        rows = json.loads(run([cli, "calendar", "--city", "北京"]))["results"]
        check("calendar-city", [r["id"] for r in rows] == ["beijing-open"])
        rows = json.loads(run([cli, "calendar", "--city", "北京", "--include-expired"]))["results"]
        check("calendar-history", {r["id"] for r in rows} == {"beijing-open", "beijing-ended"})
        rows = json.loads(run([cli, "search", "--deadline-before", info["deadline"]]))["results"]
        check("search-deadline", [r["id"] for r in rows] == ["smoke:1"])
        response = json.loads(run([cli, "search", "--company", "中核"]))
        check("company-alias", response["company_match"]["match"] == "alias"
              and len(response["results"]) == 2)
        check("source-catalog", info["catalog_entries"] > 0 and info["catalog_kinds"] == ["aggregator", "official"])
        check("packaged-category-rules", info["finance_category"] == ["职能", "财务审计"])
        response = json.loads(run([cli, "search", "--cities", "苏州", "无锡", "--exclude-city", "上海", "--category", "财务"]))
        check("category-alias-with-legacy-label", response["total"] == 2
              and response["category_match"]["match"] == "alias"
              and "财务审计" in response["category_match"]["matched"])
        response = json.loads(run([cli, "search", "--type", "intern"]))
        check("intern-frontline-default", response["total"] == 0 and response["frontline_filter"]["excluded_records"] == 1)
        response = json.loads(run([cli, "search", "--type", "intern", "--include-frontline"]))
        check("frontline-explicit-inclusion", response["total"] == 1)
        response = json.loads(run([cli, "search", "--type", "campus", "--exclude-category", "财务"]))
        check("category-exclusion", response["total"] == 0)
        run([mcp, "--help"])
        print(json.dumps({"version": info["version"], "direct_url": info["direct_url"],
                          "checks_passed": len(checks), "checks": checks, "mcp_help": "passed"},
                         ensure_ascii=False))


if __name__ == "__main__":
    main()
