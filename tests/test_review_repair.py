import importlib.util
import json
from pathlib import Path

from helpers import T, make_job
from jobradar.pipeline.ingest import ingest_run, upsert_texts

spec = importlib.util.spec_from_file_location("review_repair", Path(__file__).resolve().parents[1] / "scripts/repair_reviewed_data.py")
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


def test_cohort_withdrawal_preserves_observation_state_and_text_and_is_idempotent(jobs_db, text_db):
    evidence = json.loads((Path(__file__).parents[1] / "targets/cohort_title_corrections.json").read_text(encoding="utf-8"))["rows"][0]
    job = make_job(evidence["source_job_id"], source_id=evidence["source_id"], title=evidence["title"],
                   url=evidence["url"], grad_year=evidence["grad_year"], requirements="原岗位要求")
    ingest_run(jobs_db, job.source_id, [job], ts=T(1))
    upsert_texts(text_db, [job], ts=T(1))
    before = dict(jobs_db.execute("SELECT * FROM job").fetchone())
    text_before = tuple(text_db.execute("SELECT * FROM job_text").fetchone())
    runs_before = tuple(jobs_db.execute("SELECT * FROM source_run").fetchone())
    assert repair.withdraw_cohort_fixes(jobs_db, text_db, ts=T(2), corrections=[evidence])["changed"] == 1
    assert dict(jobs_db.execute("SELECT * FROM job").fetchone()) == before
    assert repair.withdraw_cohort_fixes(jobs_db, text_db, ts=T(2), apply=True, corrections=[evidence])["changed"] == 1
    after = dict(jobs_db.execute("SELECT * FROM job").fetchone())
    assert after["grad_year"] is None and after["content_hash"] != before["content_hash"]
    assert {k:v for k,v in after.items() if k not in {"grad_year", "content_hash"}} == {k:v for k,v in before.items() if k not in {"grad_year", "content_hash"}}
    assert tuple(text_db.execute("SELECT * FROM job_text").fetchone()) == text_before
    assert tuple(jobs_db.execute("SELECT * FROM source_run").fetchone()) == runs_before
    count = jobs_db.execute("SELECT COUNT(*) FROM job_event").fetchone()[0]
    assert repair.withdraw_cohort_fixes(jobs_db, text_db, ts=T(3), apply=True, corrections=[evidence])["changed"] == 0
    assert jobs_db.execute("SELECT COUNT(*) FROM job_event").fetchone()[0] == count


def test_cohort_withdrawal_cannot_override_changed_title_evidence(jobs_db, text_db):
    evidence = json.loads((Path(__file__).parents[1] / "targets/cohort_title_corrections.json").read_text(encoding="utf-8"))["rows"][0]
    job = make_job(evidence["source_job_id"], source_id=evidence["source_id"], title="2028届研发工程师",
                   url=evidence["url"], grad_year=2028)
    ingest_run(jobs_db, job.source_id, [job], ts=T(1))
    before = tuple(jobs_db.execute("SELECT * FROM job").fetchone())
    report = repair.withdraw_cohort_fixes(jobs_db, text_db, ts=T(2), apply=True, corrections=[evidence])
    assert report["changed"] == 0 and report["source_changed"] == 1
    assert tuple(jobs_db.execute("SELECT * FROM job").fetchone()) == before


def test_review_repair_preserves_observation_and_status_and_is_idempotent(jobs_db, text_db):
    samples = [
        make_job(1, source_id="beisen-ghbank", company="华夏银行"),
        make_job(2, source_id="unrelated", company="华夏银行"),
        make_job(3, source_id="yunjiuye-demo", description="[v-cloak]{} :root{} PAGE_THEME.colors=[] 岗位职责：负责产品研发。"),
        make_job(4, source_id="hotjob-422dbe", grad_year=None, degree_min=None,
                 requirements="2027年应届毕业生，硕士研究生及以上学历"),
    ]
    for job in samples:
        ingest_run(jobs_db, job.source_id, [job], ts=T(1))
    upsert_texts(text_db, samples, ts=T(1))
    before = [(r["id"], r["last_seen"], r["closed_at"], r["miss_count"]) for r in jobs_db.execute("SELECT * FROM job ORDER BY id")]
    assert repair.apply_fixes(jobs_db, text_db, ts=T(2))["changed"] == 3
    assert jobs_db.execute("SELECT c.name FROM job j JOIN company c ON c.id=j.company_id WHERE j.source_id='beisen-ghbank'").fetchone()[0] == "华夏银行"
    report = repair.apply_fixes(jobs_db, text_db, ts=T(2), apply=True)
    assert report["changed"] == 3
    assert repair.apply_fixes(jobs_db, text_db, ts=T(3), apply=True)["changed"] == 0
    after = [(r["id"], r["last_seen"], r["closed_at"], r["miss_count"]) for r in jobs_db.execute("SELECT * FROM job ORDER BY id")]
    assert before == after
    assert jobs_db.execute("SELECT c.name FROM job j JOIN company c ON c.id=j.company_id WHERE j.source_id='beisen-ghbank'").fetchone()[0] == "广东华兴银行"
    assert jobs_db.execute("SELECT c.name FROM job j JOIN company c ON c.id=j.company_id WHERE j.source_id='unrelated'").fetchone()[0] == "华夏银行"
    assert text_db.execute("SELECT description FROM job_text WHERE job_id='yunjiuye-demo:3'").fetchone()[0] == "岗位职责：负责产品研发。"


def test_css_comment_residual_is_not_treated_as_business_heading():
    text = ('职位描述 / 单位简介富文本 */ .job-desc { color: #3a4557; font-size: 14px; } '
            '首页 国家大学生就业服务平台 {{ job.job_desc }}')
    assert repair.clean_saved_jd(text) is None


def test_legitimate_frontend_requirement_is_not_css_pollution():
    text = "岗位职责：开发前端。任职要求：熟悉 CSS font-size:、color: 与组件开发。"
    assert repair.clean_saved_jd(text) == text


def test_reviewed_malformed_external_url_is_fixed_without_claiming_new_observation(jobs_db,text_db):
    row=make_job(123,source_id='tencent',url='https:////tencent.wd1.myworkdayjobs.com/Tencent_Careers/job/Engineer_R104904')
    ingest_run(jobs_db,'tencent',[row],ts=T(1))
    before=tuple(jobs_db.execute('SELECT last_seen,closed_at,miss_count FROM job').fetchone())
    report=repair.apply_fixes(jobs_db,text_db,ts=T(2),apply=True)
    assert report['url']==1
    assert jobs_db.execute('SELECT url FROM job').fetchone()[0]=='https://tencent.wd1.myworkdayjobs.com/Tencent_Careers/job/Engineer_R104904'
    assert tuple(jobs_db.execute('SELECT last_seen,closed_at,miss_count FROM job').fetchone())==before
    assert repair.apply_fixes(jobs_db,text_db,ts=T(3),apply=True)['changed']==0
