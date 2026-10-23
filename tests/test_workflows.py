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

def test_all_workflows_parse():
    """所有工作流必须能被 YAML 解析：改坏一个文件会让整个流水线静默不跑。"""
    files = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    assert len(files) >= 10
    for f in files:
        doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert isinstance(doc.get("jobs"), dict) and doc["jobs"], f.name


def test_publish_workflow_uses_trusted_publishing():
    """PyPI 发布走 OIDC（不存 token）：缺 id-token 权限会直接失败，这条测试守着它。"""
    doc = yaml.safe_load((ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8"))
    job = doc["jobs"]["publish-pypi"]
    assert job["permissions"]["id-token"] == "write"
    assert job["environment"] == "pypi"
    assert any("pypa/gh-action-pypi-publish" in step.get("uses", "") for step in job["steps"])


def test_mirror_verification_uses_size_checker():
    """镜像校验必须比较大小（Gitee 删除单个大附件不生效，会出现"假成功"）。"""
    doc = yaml.safe_load((ROOT / ".github" / "workflows" / "mirror.yml").read_text(encoding="utf-8"))
    steps = doc["jobs"]["mirror"]["steps"]
    check = next(s for s in steps if "download check" in (s.get("name") or ""))
    assert "verify_gitee.py" in check["run"]
