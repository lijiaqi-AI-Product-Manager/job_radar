from pathlib import Path

import yaml

EVALS = Path(__file__).parent.parent / "evals"
KNOWN_CHECKS = {
    "cite_source", "state_updated_at", "only_from_data", "no_fabrication", "say_not_found",
    "say_not_found_if_missing", "respect_limit", "use_event_data", "use_jd_text_only",
    "separate_quoted_vs_inferred", "state_data_span", "distinguish_closed_vs_missing",
    "ask_to_update_if_stale", "use_status_data", "refuse_out_of_scope",
}
TYPES = {"lookup", "diff", "compare", "trend", "freshness", "negative"}


def load():
    return yaml.safe_load((EVALS / "questions.yaml").read_text(encoding="utf-8"))


def test_questions_are_well_formed():
    qs = load()
    assert len(qs) >= 20
    assert len({q["id"] for q in qs}) == len(qs), "题目 id 重复"
    for q in qs:
        assert q["type"] in TYPES and q["question"].strip() and q["checks"]
        assert set(q["checks"]) <= KNOWN_CHECKS, f"{q['id']} 含未知 check"
        assert q["id"].startswith(q["type"][:3]) or q["id"].startswith("fresh")


def test_every_check_in_readme_is_documented():
    readme = (EVALS / "README.md").read_text(encoding="utf-8")
    for c in KNOWN_CHECKS:
        assert f"`{c}`" in readme, f"README 缺少 check 说明：{c}"
