"""预演或应用固定职类归一化；只修改派生分类，不刷新观测、状态或招聘事件。"""

import argparse
import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from jobradar.normalize import canonical_category  # noqa: E402
from jobradar.store.validate import validate_database  # noqa: E402
from jobradar.timeutil import now_ts  # noqa: E402


def _public_change(change):
    return {key:value for key,value in change.items() if not key.startswith('_')}


def _write_audit(path, changes):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 完整写入并刷盘后才改数据库；已有文件不覆盖，也不要求硬链接能力。
    with path.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump({'version':1, 'kind':'derived-category-plan', 'created_at':now_ts(),
                   'changes':[_public_change(change) for change in changes]},
                  handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())


def repair_categories(conn, *, apply=False, audit_path=None):
    source_cursor = conn.execute('SELECT MAX(id) FROM source_run').fetchone()[0]
    changes = []
    for row in conn.execute('SELECT id,title,category,subcategory,content_hash FROM job ORDER BY id'):
        jid, title, category, subcategory, content_hash = tuple(row)
        normalized = canonical_category(title, category, subcategory)
        if normalized != (category, subcategory):
            changes.append({'id':jid, 'before':{'category':category, 'subcategory':subcategory},
                            'after':{'category':normalized[0], 'subcategory':normalized[1]},
                            '_title':title, '_content_hash':content_hash})
    result = {'changed':len(changes), 'applied':0,
              'sample':[_public_change(change) for change in changes[:10]]}
    if not apply or not changes:
        return result
    if audit_path is None:
        raise ValueError('应用前需指定新的审计计划文件（--audit）')
    if conn.in_transaction:
        raise ValueError('分类维护需要独立的数据库事务')
    _write_audit(audit_path, changes)
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT MAX(id) FROM source_run').fetchone()[0] != source_cursor:
            raise ValueError('采集证据已改变，请重新预演')
        for change in changes:
            old, new = change['before'], change['after']
            cursor = conn.execute(
                'UPDATE job SET category=?,subcategory=? WHERE id=? AND title=? AND content_hash=? '
                'AND category IS ? AND subcategory IS ?',
                (new['category'], new['subcategory'], change['id'], change['_title'],
                 change['_content_hash'], old['category'], old['subcategory']))
            if cursor.rowcount != 1:
                raise ValueError('岗位证据已改变，整批分类修正已撤回')
    result['applied'] = len(changes)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--audit', type=Path, help='新的审计计划路径；保留原分类，已有文件不覆盖')
    args = parser.parse_args()
    if not args.db.is_file():
        raise SystemExit('未找到岗位数据库')
    try:
        mode = 'rw' if args.apply else 'ro'
        with closing(sqlite3.connect(args.db.resolve().as_uri()+'?mode='+mode, uri=True, timeout=30)) as conn:
            validate_database(conn, 'jobs')
            print(json.dumps(repair_categories(conn, apply=args.apply, audit_path=args.audit), ensure_ascii=False))
    except (OSError, ValueError, sqlite3.Error) as error:
        raise SystemExit(f'分类维护未完成：{error}') from None


if __name__ == '__main__':
    main()
