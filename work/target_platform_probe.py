"""把「目标清单里已知平台入口」的公司逐个探活，能直接用的写成候选。

输入 work/target_platform_picks.json（人工核对过的 company/ats/url 清单），
输出 work/target_platform_hits.json，含可用的源与跳过原因。
"""
import json
import re
import sys

sys.path.insert(0, "src")
sys.path.insert(0, "work")
import httpx
from verify_tenants_found import beisen_probe, feishu_probe, hotjob_probe

from jobradar.sources import load_sources

PICKS = json.load(open("work/target_platform_picks.json", encoding="utf-8"))
SRC = load_sources("sources")
HAVE_BEISEN = {str((s.params or {}).get("tenant", "")).lower() for s in SRC}
HAVE_HOTJOB = {str((s.params or {}).get("tenant", "")).upper() for s in SRC if "hotjob" in s.adapter}
HAVE_LEGACY = {str((s.params or {}).get("tenant", "")).lower() for s in SRC if "hotjob_legacy" in s.adapter}
HAVE_FEISHU = {
    str((s.params or {}).get("base_url", "")).split("//")[-1].split(".")[0].lower() for s in SRC
}

BEISEN_RE = re.compile(r"//([a-z0-9-]+)\.zhiye\.com", re.I)
HOTJOB_RE = re.compile(r"//([a-z0-9-]+)\.hotjob\.cn/(wt/)?", re.I)
SU_RE = re.compile(r"hotjob\.cn/(SU[0-9a-f]{10,})", re.I)
FEISHU_RE = re.compile(r"//([a-z0-9-]+)\.jobs\.feishu\.cn", re.I)


def beisen_row(client, name, url):
    m = BEISEN_RE.search(url)
    if not m or m.group(1) == "portal-oss":
        return None, "portal-oss"
    tenant = m.group(1).lower()
    if tenant in HAVE_BEISEN:
        return None, "tenant-exists"
    r = beisen_probe(client, tenant)
    if r.get("ok") and int(r.get("count") or 0) > 0:
        return {"kind": "beisen", "tenant": tenant, "company": name, "count": int(r["count"])}, None
    return None, "no-jobs"


def dayee_row(client, name, url):
    m = HOTJOB_RE.search(url)
    if m and "/wt/" in url:
        tenant = m.group(1).lower()
        if tenant in HAVE_LEGACY:
            return None, "legacy-exists"
        r = hotjob_probe(client, tenant)
        if r.get("ok") and int(r.get("count") or 0) > 0:
            host = f"{tenant}.hotjob.cn"
            row = {
                "kind": "hotjob_legacy",
                "tenant": tenant,
                "company": name,
                "count": int(r["count"]),
                "host": host,
            }
            return row, None
        return None, "legacy-dead"
    su = SU_RE.search(url)
    if not su:
        return None, "wecruit-generic"
    tenant = su.group(1).upper()
    if tenant in HAVE_HOTJOB:
        return None, "su-exists"
    r = hotjob_probe(client, tenant)
    if r.get("ok") and int(r.get("count") or 0) > 0:
        return {"kind": "hotjob", "tenant": tenant, "company": name, "count": int(r["count"])}, None
    return None, "su-no-jobs"


def feishu_row(client, name, url):
    m = FEISHU_RE.search(url)
    if not m:
        return None, "not-feishu"
    slug = m.group(1).lower()
    if slug in HAVE_FEISHU:
        return None, "feishu-exists"
    r = feishu_probe(client, slug)
    campus = int(r.get("campus") or r.get("count") or 0)
    if r.get("ok") and campus > 0:
        return {"kind": "feishu_atsx", "tenant": slug, "company": name, "count": campus}, None
    return None, "feishu-no-campus"


def main() -> int:
    rows = []
    skipped = []
    client = httpx.Client(
        headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True, timeout=25
    )
    try:
        for pick in PICKS:
            name, ats, url = pick["company"], pick["ats"], pick["url"]
            try:
                if ats == "beisen":
                    row, why = beisen_row(client, name, url)
                elif ats == "dayee":
                    row, why = dayee_row(client, name, url)
                elif ats == "feishu_atsx":
                    row, why = feishu_row(client, name, url)
                else:
                    row, why = None, "unknown-ats"
            except Exception as exc:  # 单条网络错误不中断整批
                row, why = None, type(exc).__name__
            if row:
                rows.append(row)
            else:
                skipped.append({"company": name, "why": why})
    finally:
        client.close()
    print("usable", len(rows))
    for r in rows:
        print(r["kind"], r["tenant"], r["count"], r["company"])
    print("skipped", len(skipped))
    json.dump(
        {"rows": rows, "skipped": skipped},
        open("work/target_platform_hits.json", "w", encoding="utf-8"),
        ensure_ascii=False,
        indent=1,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
