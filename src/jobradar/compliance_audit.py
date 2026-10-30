"""离线核验源配置与录制请求；不把结构检查冒充逐站法律授权或在线探活。"""

import json
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from jobradar.adapters.base import USER_AGENT
from jobradar.compliance import terms_block_reason
from jobradar.models import SourceConfig
from jobradar.timeutil import shanghai_date

SECRET_KEYS = {"token", "accesstoken", "csrftoken", "xcsrftoken", "requestverificationtoken",
               "password", "passwd", "cookie", "authorization", "sessionid"}


def _secrets(value: object, context: str) -> list[str]:
    problems = []
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = "".join(c.lower() for c in str(key) if c.isalnum())
            if normalized in SECRET_KEYS and item not in (None, "", "REDACTED", False):
                problems.append(f"{context}: 不得持久化凭据字段 {key}")
            else:
                problems.extend(_secrets(item, context))
    elif isinstance(value, list):
        for item in value:
            problems.extend(_secrets(item, context))
    return problems


def _urls(value: object) -> list[str]:
    if isinstance(value, dict):
        return [url for item in value.values() for url in _urls(item)]
    if isinstance(value, list):
        return [url for item in value for url in _urls(item)]
    return [value] if isinstance(value, str) and value.startswith(("http://", "https://")) else []


def audit_sources(sources: list[SourceConfig]) -> list[str]:
    problems = []
    for source in sources:
        if not source.enabled:
            continue
        context = source.id
        compliance = source.compliance
        if compliance is None or not compliance.robots.strip() or not compliance.terms.strip():
            problems.append(f"{context}: 缺少 robots/条款核查记录")
        elif compliance.robots.strip().lower() in {"blocked", "deny", "denied", "disallowed", "forbidden"}:
            problems.append(f"{context}: 明确禁止的源不能启用")
        problems.extend(_secrets(source.params, context))
        if source.params.get("user_agent") not in (None, USER_AGENT):
            problems.append(f"{context}: 不得按站点覆盖固定 UA")
        hosts = [urlsplit(url).hostname or "" for url in _urls(source.params)]
        host = source.params.get("host")
        if isinstance(host, str):
            hosts.append(urlsplit(host if "://" in host else "https://" + host).hostname or "")
        for hostname in set(hosts):
            if reason := terms_block_reason(hostname):
                problems.append(f"{context}: {reason}")
    return problems


def audit_manifest(path: Path, entries: list) -> list[str]:
    problems = []
    for index, row in enumerate(entries, 1):
        context = f"{path}:{index}"
        if not isinstance(row, dict):
            problems.append(f"{context}: 请求记录必须为对象")
            continue
        url = urlsplit(str(row.get("url") or ""))
        if url.username or url.password:
            problems.append(f"{context}: URL 不得保存账号凭据")
        problems.extend(_secrets(dict(parse_qsl(url.query)), context))
        body = row.get("body") or ""
        try:
            payload = json.loads(body)
        except (ValueError, TypeError):
            payload = dict(parse_qsl(str(body)))
        problems.extend(_secrets(payload, context))
        problems.extend(_secrets(row.get("headers"), context))
    return problems


def audit_source_checks(payload: object, sources: list[SourceConfig]) -> list[str]:
    """核验增补源的最小实测证据；日期与数量都只表示 checked_at 时的抽样。"""
    if (not isinstance(payload, dict) or type(payload.get("schema_version")) is not int
            or payload["schema_version"] != 1 or not isinstance(payload.get("checks"), list)):
        return ["source_checks: 必须有 schema_version: 1 与 checks 列表"]
    configured = {s.id: s for s in sources}
    seen = set()
    problems = []
    for index, row in enumerate(payload["checks"], 1):
        context = f"source_checks:{index}"
        if not isinstance(row, dict) or not isinstance(row.get("source_id"), str):
            problems.append(f"{context}: 必须为含 source_id 的对象")
            continue
        sid = row["source_id"]
        source = configured.get(sid)
        if sid in seen or source is None or not source.enabled:
            problems.append(f"{context}: 源必须唯一且已启用")
        seen.add(sid)
        if source is not None and row.get("company") != source.company:
            problems.append(f"{context}: 证据公司与源配置不一致")
        registered = row.get("registered_company")
        if not isinstance(registered, str) or not registered.strip():
            problems.append(f"{context}: 缺少核实的公司全名")
        try:
            day = shanghai_date(row.get("checked_at"))
        except (ValueError, TypeError):
            day = None
            problems.append(f"{context}: checked_at 必须为 UTC 时间戳")
        kind = row.get("record_kind", "position")
        if not isinstance(kind, str) or kind not in {"position", "recruitment_notice"}:
            problems.append(f"{context}: 未知 record_kind")
        count_field, jd_field = ("current_records", "records_with_jd") if kind == "recruitment_notice" else (
            "current_jobs", "jobs_with_jd")
        current, jd = row.get(count_field), row.get(jd_field)
        if type(current) is not int or type(jd) is not int or not 0 < jd <= current:
            problems.append(f"{context}: 抽样数必须满足 0 < {jd_field} <= {count_field}")
        samples = row.get("samples")
        if not isinstance(samples, list) or not samples:
            problems.append(f"{context}: 缺少真实岗位样本")
            continue
        for sample in samples:
            if not isinstance(sample, dict):
                problems.append(f"{context}: 岗位样本必须为对象")
                continue
            if not all(isinstance(sample.get(k), str) and sample[k].strip()
                       for k in ("source_job_id", "title", "url")):
                problems.append(f"{context}: 岗位缺少 id/标题/原始链接")
            try:
                url = urlsplit(str(sample.get("url") or ""))
                if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
                    problems.append(f"{context}: 岗位链接必须是无凭据的公开 HTTP URL")
                problems.extend(_secrets(dict(parse_qsl(url.query)), context))
            except ValueError:
                problems.append(f"{context}: 岗位链接格式错误")
            for field in ("publish_at", "apply_end", "listing_end"):
                value = sample.get(field)
                if value is None:
                    continue
                try:
                    if date.fromisoformat(value).isoformat() != value:
                        raise ValueError
                except (ValueError, TypeError):
                    problems.append(f"{context}: {field} 必须为日期或 null")
                    continue
                if field in {"apply_end", "listing_end"} and day is not None and value < day:
                    problems.append(f"{context}: 核查时记录已截止（{field}），不能作为当前样本")
    return problems
