from pathlib import Path

from jobradar.compliance_audit import audit_manifest, audit_source_checks, audit_sources
from jobradar.models import SourceConfig


def source(**updates):
    values = {"id": "example", "company": "某公司", "adapter": "example", "params": {"host": "example.com"},
              "compliance": {"checked_on": "2026-10-30", "robots": "allowed", "terms": "公开招聘页"}}
    return SourceConfig(**{**values, **updates})


def test_audit_rejects_static_credentials_and_restricted_channels_without_printing_values():
    problems = audit_sources([source(params={"host": "m.yingjiesheng.com", "csrf_token": "secret-value"})])
    assert len(problems) >= 2
    assert any("书面许可" in p for p in problems)
    assert any("凭据" in p for p in problems)
    assert "secret-value" not in str(problems)


def test_audit_accepts_redaction_and_valid_public_config():
    assert audit_sources([source(params={"host": "example.com", "csrf_token": "REDACTED"})]) == []


def test_manifest_audit_checks_json_form_and_url_tokens():
    entries = [
        {"url": "https://example.com/jobs?access_token=private", "body": ""},
        {"url": "https://example.com/jobs", "body": '{"csrf_token": "private"}'},
        {"url": "https://example.com/jobs", "body": "csrf_token=REDACTED&keyword=jobs"},
    ]
    problems = audit_manifest(Path("manifest.json"), entries)
    assert len(problems) == 2 and "private" not in str(problems)


def evidence(**updates):
    row = {"source_id": "example", "company": "某公司", "registered_company": "某公司有限公司",
           "checked_at": "2026-10-30T16:00:00Z", "current_jobs": 1, "jobs_with_jd": 1,
           "samples": [{"source_job_id": "1", "title": "工程师", "url": "https://example.com/jobs/1",
                        "publish_at": "2026-10-30", "apply_end": "2026-11-10"}]}
    return {"schema_version": 1, "checks": [{**row, **updates}]}


def test_source_checks_validate_references_identity_quality_and_checked_dates():
    assert audit_source_checks(evidence(), [source()]) == []
    assert audit_source_checks(evidence(source_id="missing"), [source()])
    assert audit_source_checks(evidence(company="另一家公司"), [source()])
    assert audit_source_checks(evidence(checked_at="2026-10-30"), [source()])
    assert audit_source_checks(evidence(current_jobs=0), [source()])
    assert audit_source_checks(evidence(jobs_with_jd=2), [source()])
    assert audit_source_checks(evidence(samples=[]), [source()])
    assert audit_source_checks(evidence(current_jobs=True), [source()])


def test_source_checks_do_not_accept_expired_or_credential_samples():
    # 核查时刻已经是北京时间 31 日，30 日截止的岗位不能作为当时的在招证据。
    samples = [{"source_job_id": "1", "title": "工程师", "url": "https://example.com/jobs/1?token=private",
                "publish_at": "2026-10-30", "apply_end": "2026-10-30"}]
    problems = audit_source_checks(evidence(samples=samples), [source()])
    assert any("截止" in p for p in problems)
    assert any("凭据" in p for p in problems)
    assert "private" not in str(problems)


def test_source_checks_reject_malformed_and_duplicate_rows():
    assert audit_source_checks(None, [source()])
    assert audit_source_checks({"schema_version": 1, "checks": [None]}, [source()])
    payload = evidence()
    payload["checks"] *= 2
    assert audit_source_checks(payload, [source()])


def test_audit_rejects_configured_user_agent_override():
    assert any("UA" in p for p in audit_sources([source(params={"user_agent": "different-agent"})]))


def test_announcement_evidence_uses_record_counts_without_claiming_single_jobs():
    payload = evidence(record_kind="recruitment_notice", current_records=1, records_with_jd=1)
    payload["checks"][0].pop("current_jobs")
    payload["checks"][0].pop("jobs_with_jd")
    assert audit_source_checks(payload, [source()]) == []
    assert audit_source_checks(evidence(record_kind="advertisement"), [source()])


def test_expired_school_notice_is_not_valid_current_evidence():
    payload = evidence(record_kind="recruitment_notice", current_records=1, records_with_jd=1)
    payload["checks"][0]["samples"][0]["listing_end"] = "2026-10-30"
    assert any("截止" in p for p in audit_source_checks(payload, [source()]))
