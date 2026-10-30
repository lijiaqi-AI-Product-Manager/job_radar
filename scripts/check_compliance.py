"""离线核验全部启用源的合规记录、已知条款限制与 fixtures 请求凭据；真实请求另有 robots 守卫。"""

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobradar.compliance_audit import audit_manifest, audit_source_checks, audit_sources  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=ROOT / "sources")
    parser.add_argument("--fixtures", type=Path, default=ROOT / "tests/fixtures")
    parser.add_argument("--source-checks", type=Path, default=ROOT / "targets/source_checks.yaml")
    args = parser.parse_args()
    sources = load_sources(args.sources)
    problems = audit_sources(sources)
    try:
        payload = yaml.safe_load(args.source_checks.read_text(encoding="utf-8-sig"))
        problems.extend(audit_source_checks(payload, sources))
    except (OSError, ValueError, yaml.YAMLError):
        problems.append(f"{args.source_checks}: 无法读取增补源证据")
    manifests = sorted(args.fixtures.rglob("manifest.json"))
    for path in manifests:
        try:
            entries = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            problems.append(f"{path}: 无法读取请求记录")
            continue
        if not isinstance(entries, list):
            problems.append(f"{path}: 请求记录必须为列表")
            continue
        problems.extend(audit_manifest(path, entries))
    print(f"sources={len(sources)} manifests={len(manifests)} problems={len(problems)}")
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
