import hashlib
import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

RecruitType = Literal["campus", "intern", "social"]


class Job(BaseModel):
    """适配器 normalize() 的唯一输出格式。字段含义见 docs/DESIGN 与 migrations/jobs/0001_init.sql。"""

    source_id: str
    source_job_id: str
    company: str
    url: str
    title: str = Field(min_length=1)
    recruit_type: RecruitType
    category: str | None = None
    subcategory: str | None = None
    grad_year: int | None = None
    batch: str | None = None
    cities: list[str] = Field(default_factory=list)
    degree_min: str | None = None
    department: str | None = None
    # 原文，进 jd_text.db，不进主库
    description: str | None = None
    requirements: str | None = None

    @property
    def id(self) -> str:
        return f"{self.source_id}:{self.source_job_id}"

    def content_hash(self) -> str:
        payload = self.model_dump(exclude={"source_id", "source_job_id", "company"})
        payload["cities"] = sorted(self.cities)
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha1(raw.encode()).hexdigest()


class Compliance(BaseModel):
    """每个源必须登记：谁、何时、查过什么。见 COMPLIANCE.md。"""

    checked_on: date
    robots: str
    terms: str
    notes: str = ""


class SourceConfig(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    company: str
    adapter: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    params: dict = Field(default_factory=dict)
    recruit_types: list[RecruitType] = Field(default_factory=lambda: ["campus"])
    enabled: bool = True
    rate_limit_rps: float = Field(default=1.0, gt=0, le=5)
    compliance: Compliance | None = None

    @model_validator(mode="after")
    def _enabled_needs_compliance(self):
        if self.enabled and self.compliance is None:
            raise ValueError(f"source {self.id}: enabled sources must have a compliance record")
        return self

    @property
    def max_pages(self) -> int | None:
        return self.params.get("max_pages")
