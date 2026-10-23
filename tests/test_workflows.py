"""工作流契约：daily 里几条「曾经静默出错」的保障不能再丢。

背景（2026-10-23）：
- daily #12 之前，`crawl` 没有预算上限，跑到 100 分钟被 GitHub 掐断；
- 日历步骤串行探活常年 30 分钟超时，`continue-on-error` 让它静默沿用旧 calendar.db，
  发布里的日历连续几轮没更新却全绿。
这些修复都写在工作流里，没有单元测试守着，很容易在某次改 YAML 时被抹掉。
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
DAILY = yaml.safe_load((ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8"))


def _steps() -> list[dict]:
    job = DAILY["jobs"][next(iter(DAILY["jobs"]))]
    return job["steps"]


def _step(name: str) -> dict:
    return next(s for s in _steps() if s.get("name") == name)


def test_crawl_has_time_budget():
    """没有预算时，抓取会超过 GitHub 的作业上限被硬杀，一个源都发不出去。"""
    run = _step("Crawl")["run"]
    assert "--budget-seconds" in run


def test_calendar_step_asserts_freshness():
    """日历步骤必须在上传后校验 build 时间戳，避免"超时了但没人发现"。"""
    run = _step("Build recruiting calendar")["run"]
    assert "--check-links" in run
    assert "SELECT MAX(ts) FROM build" in run
    assert "sys.exit" in run
