import json
from pathlib import Path

import pytest

from jobradar.discovery import parse_nowcoder_schedule

FIXTURE = Path(__file__).parent / "fixtures/nowcoder_discovery/schedule.html"


def test_public_schedule_extracts_only_facts_and_does_not_claim_coverage():
    result = parse_nowcoder_schedule(FIXTURE.read_text(encoding="utf-8"))
    assert result["current_page"] == 1 and result["total_pages"] > 1
    assert len(result["leads"]) == 3
    first = result["leads"][0]
    assert first["company"] == "厦门银行" and first["company_id"] == "2932"
    assert "厦门" in first["cities"]
    assert first["careers_url"].startswith("https://app.mokahr.com/")
    assert first["source_kind"] == "aggregator" and first["ownership_verified"] is False
    assert set(first) == {"company", "company_id", "cities", "careers_url", "apply_start", "apply_end",
                          "batch", "source_url", "source_kind", "ownership_verified"}


@pytest.mark.parametrize("html", ["<html>captcha</html>", "window.__INITIAL_STATE__=function(){return 1}();"])
def test_missing_or_executable_state_is_not_treated_as_an_empty_list(html):
    with pytest.raises(ValueError):
        parse_nowcoder_schedule(html)


def test_parser_uses_shanghai_dates_and_drops_unsafe_urls_and_private_fields():
    payload = {"app": {"changed-module-id": {"scheduleData": {"currentPage": 2, "totalPage": 2, "datas": [{
        "name": "某公司", "companyId": 123, "cityList": ["北京", "北京"],
        "customWangshenLink": "https://user:secret@example.com/apply", "wangshenEndDate": 1793376000000,
        "companyEvaluation": "do not copy creative text", "user": {"phone": "do not copy"},
    }]}}}}
    lead = parse_nowcoder_schedule("window.__INITIAL_STATE__=" + json.dumps(payload) + ";")["leads"][0]
    assert lead["careers_url"] is None
    assert lead["apply_end"] == "2026-10-31" and lead["cities"] == ["北京"]
    assert "do not copy" not in json.dumps(lead)
