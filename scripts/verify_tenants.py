"""批量验证北森租户：{tenant}.zhiye.com 是否有在招岗位，能拿多少条。

用法：
    uv run python scripts/verify_tenants.py tenants.json out.json [--workers 4]

tenants.json: {"tenant": "公司名", ...}（也接受 proposed-sources.yaml 里的 company 作备注）

判定口径（2026-10-26 与 sources/beisen.yaml 的适配器一致）：
  POST https://{tenant}.zhiye.com/api/Jobad/GetJobAdPageList
  body {"PageIndex":1,"PageSize":1,"KeyWords":"","SpecialType":0,"PortalId":""}
  -> {"Code":200,...} 里 Count 就是该租户的岗位总数；Code!=200 或非 JSON 视为不可用。

限速：同一域名后缀串行 1 req/s（北森所有租户共用一个 API 域名族，不并发打）。
因此这里用单线程 + sleep，不用线程池——并发会给 zhiye.com 造成突发压力。
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

API = "https://{tenant}.zhiye.com/api/Jobad/GetJobAdPageList"
BODY = {"PageIndex": 1, "PageSize": 1, "KeyWords": "", "SpecialType": 0, "PortalId": ""}
UA = "Mozilla/5.0 (compatible; jobradar-bot/0.1)"


def probe(client: httpx.Client, tenant: str) -> dict:
    try:
        r = client.post(API.format(tenant=tenant), json=BODY)
        if r.status_code != 200:
            return {"tenant": tenant, "ok": False, "reason": f"http {r.status_code}"}
        d = r.json()
        code = d.get("Code")
        if code != 200:
            # 常见：老版门户（/api/Jobad/… 不存在）、租户已停用、需要 Referer
            return {"tenant": tenant, "ok": False, "reason": f"code {code} {str(d.get('Message'))[:40]}"}
        return {"tenant": tenant, "ok": True, "count": int(d.get("Count") or 0)}
    except ValueError:
        return {"tenant": tenant, "ok": False, "reason": "非 JSON（多半是老版门户）"}
    except Exception as e:
        return {"tenant": tenant, "ok": False, "reason": f"{type(e).__name__}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tenants")
    ap.add_argument("out")
    ap.add_argument("--interval", type=float, default=1.0, help="每个租户之间的间隔秒数（默认 1s）")
    args = ap.parse_args()

    tenants = json.loads(Path(args.tenants).read_text(encoding="utf-8"))
    if isinstance(tenants, list):
        tenants = {t: "" for t in tenants}
    print(f"待验证 {len(tenants)} 个租户", file=sys.stderr)

    out = []
    with httpx.Client(headers={"User-Agent": UA}, timeout=15, follow_redirects=True) as c:
        for i, (tenant, company) in enumerate(tenants.items(), 1):
            res = probe(c, tenant)
            res["company"] = company
            out.append(res)
            if i % 20 == 0:
                ok = sum(1 for x in out if x["ok"])
                print(f"  {i}/{len(tenants)}，可用 {ok}", file=sys.stderr)
            time.sleep(args.interval)

    out.sort(key=lambda x: (-x["ok"], -(x.get("count") or 0)))
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    ok = [x for x in out if x["ok"] and x.get("count")]
    empty = [x for x in out if x["ok"] and not x.get("count")]
    bad = [x for x in out if not x["ok"]]
    print(f"\n可用且有岗位 {len(ok)} 个，可用但 0 岗 {len(empty)} 个，不可用 {len(bad)} 个", file=sys.stderr)
    print(f"岗位合计 {sum(x['count'] for x in ok)} 条", file=sys.stderr)
    for x in ok[:25]:
        print(f"  {x['count']:5d}  {x['tenant']:20s} {x.get('company') or ''}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
