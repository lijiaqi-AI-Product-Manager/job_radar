from jobradar.models import Job


def T(day: int, hour: int = 0) -> str:
    return f"2026-10-{day:02d}T{hour:02d}:00:00Z"


def make_job(n: int = 1, **kw) -> Job:
    base = dict(
        source_id="s1",
        source_job_id=str(n),
        company="腾讯",
        url=f"https://careers.example.invalid/job/{n}",
        title=f"后端开发工程师 {n}",
        recruit_type="campus",
        category="技术",
        subcategory="后端",
        grad_year=2027,
        batch="正式批",
        cities=["深圳"],
        degree_min="本科",
        department="测试部",
    )
    base.update(kw)
    return Job(**base)
