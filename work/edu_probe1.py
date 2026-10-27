"""第一轮：只读 HTTP 探测，筛出 /campus 返回 200 且确实带 /campus/view/id/N 的 host。"""
import json
import os  # noqa: E402
import re
import subprocess
import time
from pathlib import Path

UA = ("jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; open dataset, "
      "polite crawler; contact via GitHub issues)")
W = Path(__file__).parent

SRC = os.environ.get("HOSTFILE", "edu_hosts_all.txt")
OUT = os.environ.get("OUTFILE", "edu_probe1")
hosts = [h.strip() for h in (W / SRC).read_text().split() if h.strip()]
hosts = [h for h in hosts if not h.endswith("edu.cn/") and "." in h]

out = []
log = open(W / (OUT + ".log"), "w")
for _i, h in enumerate(hosts):
    url = f"https://{h}/campus"
    try:
        p = subprocess.run(
            ["curl", "-s", "-L", "-A", UA, "--max-time", "12",
             "-w", "\n__CODE__%{http_code}", url],
            capture_output=True, text=True, timeout=20)
        raw = p.stdout
        if "__CODE__" in raw:
            body, code = raw.rsplit("\n__CODE__", 1)
        else:
            body, code = raw, "000"
    except Exception:
        body, code = "", "ERR"
    n = len(set(re.findall(r"/campus/view/id/(\d+)", body)))
    has_mark = "过期时间" in body
    rec = {"host": h, "code": code, "items": n, "expire_in_html": has_mark, "len": len(body)}
    out.append(rec)
    log.write(json.dumps(rec, ensure_ascii=False) + "\n")
    log.flush()
    if n or code != "200":
        print(rec, flush=True)
    time.sleep(1.0)

(W / (OUT + ".json")).write_text(json.dumps(out, ensure_ascii=False, indent=1))
print("done", len(out))
