"""导出适合 Release 分发的兼容数据库；不修改抓取工作库。"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from jobradar.release_export import export_database  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=ROOT / 'data')
    parser.add_argument('--out', type=Path, default=ROOT / 'data/public')
    args = parser.parse_args()
    for kind, name in (('jobs', 'jobs.db'), ('text', 'jd_text.db')):
        export_database(args.home / name, args.out / name, kind)
        print(f'{name}: compatible export verified')


if __name__ == '__main__':
    main()
