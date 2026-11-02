"""在快照副本上应用已审核的主体、模板正文与华泰字段修正，不伪造抓取时间。"""

import argparse
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from jobradar.adapters.hotjob import verified_detail_fields
from jobradar.adapters.tencent import public_post_url
from jobradar.jd_text import template_pollution
from jobradar.models import Job
from jobradar.normalize import normalize_cities
from jobradar.pipeline.ingest import _event
from jobradar.timeutil import now_ts


def clean_saved_jd(text):
    if not template_pollution(text):
        return text
    # CSS注释中的“职位描述”不是正文起点；这类残留无法从丢失DOM的文本可靠还原。
    if ".job-desc" in text and "单位简介富文本" in text[:150]:
        return None
    match = re.search(r"(?:岗位职责|工作职责|职位描述|任职要求)\s*[:：]", text)
    if not match:
        return None
    body = re.split(r"单位信息|联系方式|相关职位|版权所有", text[match.start():], maxsplit=1)[0]
    return body.strip() or None


def apply_fixes(jobs, texts, *, ts, apply=False):
    report = dict(changed=0, owner=0, jd=0, cities=0, grad_year=0, degree_min=0, url=0)
    rows = jobs.execute(
        "SELECT j.*, c.name AS company FROM job j JOIN company c ON c.id=j.company_id "
        "WHERE j.source_id IN ('beisen-ghbank','hotjob-422dbe','tencent') OR j.source_id LIKE 'yunjiuye-%' "
        "OR j.cities LIKE '%市%' OR j.cities LIKE '%TP%' OR j.cities LIKE '%,%'").fetchall()
    former_owners = set()
    with jobs, texts:
        for row in rows:
            body = texts.execute("SELECT description, requirements FROM job_text WHERE job_id=?", (row["id"],)).fetchone()
            description, requirements = body if body else (None, None)
            values = {k: row[k] for k in Job.model_fields if k in row.keys()}
            values.update(company=row["company"], cities=json.loads(row["cities"]),
                          description=description, requirements=requirements)
            fields = []
            if row['source_id']=='tencent':
                corrected_url=public_post_url(values['url'],row['source_job_id'])
                if corrected_url!=values['url']:
                    values['url']=corrected_url
                    fields.append('url')
                    report['url']+=1
            normalized_cities = normalize_cities(values["cities"])
            if normalized_cities != values["cities"]:
                values["cities"] = normalized_cities
                fields.append("cities")
                report["cities"] += 1
            if row["source_id"] == "beisen-ghbank" and row["company"] != "广东华兴银行":
                former_owners.add(row["company_id"])
                values["company"] = "广东华兴银行"
                fields.append("company")
                report["owner"] += 1
            if row["source_id"].startswith("yunjiuye-"):
                values["description"] = clean_saved_jd(description)
                values["requirements"] = clean_saved_jd(requirements)
                if (values["description"], values["requirements"]) != (description, requirements):
                    fields.append("text")
                    report["jd"] += 1
            if row["source_id"] == "hotjob-422dbe":
                evidence = verified_detail_fields(requirements or "")
                for name in ("grad_year", "degree_min"):
                    if name == "grad_year" and row["recruit_type"] == "social":
                        continue
                    if values.get(name) is None and evidence[name] is not None:
                        values[name] = evidence[name]
                        fields.append(name)
                        report[name] += 1
            if not fields:
                continue
            report["changed"] += 1
            if not apply:
                continue
            job = Job(**values)
            jobs.execute("INSERT OR IGNORE INTO company(name) VALUES (?)", (job.company,))
            company_id = jobs.execute("SELECT id FROM company WHERE name=?", (job.company,)).fetchone()[0]
            jobs.execute("UPDATE job SET company_id=?, grad_year=?, degree_min=?, cities=?, url=?, content_hash=? WHERE id=?",
                         (company_id, job.grad_year, job.degree_min, json.dumps(job.cities, ensure_ascii=False), job.url, job.content_hash(), row["id"]))
            if "text" in fields:
                texts.execute("UPDATE job_text SET description=?, requirements=? WHERE job_id=?",
                              (job.description, job.requirements, row["id"]))
            _event(jobs, row["id"], ts, "change", {"fields": fields, "reason": "reviewed data correction"})
        if apply:
            for company_id in former_owners:
                jobs.execute("DELETE FROM company WHERE id=? AND NOT EXISTS "
                             "(SELECT 1 FROM job WHERE company_id=?)", (company_id, company_id))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with closing(sqlite3.connect((args.home / "jobs.db").resolve().as_uri() + "?mode=rw", uri=True)) as jobs, \
            closing(sqlite3.connect((args.home / "jd_text.db").resolve().as_uri() + "?mode=rw", uri=True)) as texts:
        jobs.row_factory = sqlite3.Row
        for connection in (jobs, texts):
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("snapshot integrity check failed")
        print(json.dumps(apply_fixes(jobs, texts, ts=now_ts(), apply=args.apply), ensure_ascii=False))


if __name__ == "__main__":
    main()
