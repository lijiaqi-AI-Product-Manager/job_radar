"""未完成采集的详情进度：不写岗位状态，只复用已读取的规范化正文。"""

import hashlib
import inspect
import json
import os
import re
import tempfile
from datetime import timedelta
from pathlib import Path

from jobradar.file_lock import file_lock
from jobradar.jd_text import template_pollution
from jobradar.models import Job
from jobradar.timeutil import parse_ts

MAX_RECORD_BYTES = 2 * 1024 ** 2
MAX_SOURCE_BYTES = 64 * 1024 ** 2
MAX_SOURCE_ENTRIES = 20_000


class DetailCheckpoint:
    def __init__(self, root, source, adapter, ts):
        self.source, self.ts = source, ts
        self.directory, self.entries, self.used, self.loaded = None, {}, 0, False
        self.hours = source.params.get('detail_cache_hours', 0)
        if source.adapter not in {'hotjob', 'shixiseng'} or type(self.hours) is not int or not 0 < self.hours <= 168:
            return
        try:
            root = Path(root)
            root.mkdir(parents=True, exist_ok=True)
            if root.is_symlink() or root.resolve().parent != root.parent.resolve():
                return
            directory = root / source.id
            directory.mkdir(exist_ok=True)
            if directory.is_symlink() or directory.resolve().parent != root.resolve():
                return
            settings = json.dumps({'id': source.id, 'company': source.company, 'adapter': source.adapter,
                'params': source.params, 'recruit_types': source.recruit_types}, sort_keys=True, separators=(',', ':')).encode()
            self.signature = hashlib.sha256(settings + Path(inspect.getfile(adapter)).read_bytes()).hexdigest()
            self.directory = directory
        except (OSError, TypeError, ValueError):
            pass  # 辅助进度不可用时仍执行正常完整采集。

    def load(self):
        self.loaded, self.entries, self.used = True, {}, 0
        if self.directory is None:
            return self.entries
        try:
            if (self.directory / '.lock').is_symlink():
                return self.entries
            with file_lock(self.directory / '.lock', timeout=0):
                for index, path in enumerate(self.directory.glob('*.json')):
                    if index >= MAX_SOURCE_ENTRIES * 2:
                        break
                    try:
                        if (path.is_symlink() or path.resolve().parent != self.directory.resolve()
                                or not re.fullmatch(r'[a-f0-9]{64}\.json', path.name)):
                            continue
                        size = path.stat().st_size
                        if size > MAX_RECORD_BYTES or self.used + size > MAX_SOURCE_BYTES:
                            continue
                        entry = json.loads(path.read_text(encoding='utf-8'))
                        if (not isinstance(entry, dict) or set(entry) != {'version', 'signature', 'job', 'observed_at'}
                                or type(entry.get('version')) is not int or entry['version'] != 1
                                or entry.get('signature') != self.signature
                                or not isinstance(entry.get('job'), dict) or set(entry['job']) - set(Job.model_fields)):
                            path.unlink(missing_ok=True)
                            continue
                        job = Job.model_validate(entry['job'])
                        observed, current = parse_ts(entry['observed_at']), parse_ts(self.ts)
                        if (job.source_id != self.source.id or job.company != self.source.company
                                or path.name != hashlib.sha256(job.id.encode()).hexdigest() + '.json'
                                or observed > current or current - observed > timedelta(hours=self.hours)):
                            path.unlink(missing_ok=True)
                            continue
                        self.entries[job.source_job_id] = {**job.model_dump(), 'cities': json.dumps(job.cities, ensure_ascii=False),
                                                           'fetched_at': entry['observed_at']}
                        self.used += size
                    except (OSError, ValueError, KeyError, TypeError):
                        continue
        except (OSError, ValueError):
            pass
        return self.entries

    def record(self, job):
        if (self.directory is None or (self.directory / '.lock').is_symlink()
                or job.source_id != self.source.id or job.company != self.source.company
                or job.text_observed_at or not (job.description or job.requirements)
                or any(template_pollution(v) for v in (job.description, job.requirements))):
            return
        if not self.loaded:
            self.load()
        if len(self.entries) >= MAX_SOURCE_ENTRIES and job.source_job_id not in self.entries:
            return
        temporary = None
        try:
            payload = json.dumps({'version': 1, 'signature': self.signature, 'observed_at': self.ts,
                                  'job': job.model_dump(mode='json')}, ensure_ascii=False).encode('utf-8')
            if len(payload) > MAX_RECORD_BYTES or self.used + len(payload) > MAX_SOURCE_BYTES:
                return
            path = self.directory / (hashlib.sha256(job.id.encode()).hexdigest() + '.json')
            if path.is_symlink():
                return
            with file_lock(self.directory / '.lock', timeout=0):
                if path.exists() and path.stat().st_size <= MAX_RECORD_BYTES:
                    try:
                        old = json.loads(path.read_text(encoding='utf-8'))
                        if isinstance(old, dict) and old.get('signature') == self.signature and parse_ts(old['observed_at']) > parse_ts(self.ts):
                            return
                    except (OSError, ValueError, KeyError, TypeError):
                        pass
                with tempfile.NamedTemporaryFile(dir=self.directory, suffix='.part', delete=False) as handle:
                    temporary = Path(handle.name)
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                previous = path.stat().st_size if path.exists() and job.source_job_id in self.entries else 0
                os.replace(temporary, path)
                self.used += len(payload) - previous
                self.entries[job.source_job_id] = {**job.model_dump(), 'cities': json.dumps(job.cities, ensure_ascii=False),
                                                   'fetched_at': self.ts}
        except (OSError, ValueError, TypeError):
            pass
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
