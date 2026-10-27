"""第二轮：多线程（8 并发）+ 单线程内串行，筛 /campus 是否返回带 /campus/view/id/N 的页面。"""
import json
import queue
import re
import subprocess
import threading
import time
from pathlib import Path

UA = ("jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; open dataset, "
      "polite crawler; contact via GitHub issues)")
W = Path(__file__).parent
hosts = [h.strip() for h in (W / "edu_cand_live.txt").read_text().split() if h.strip()]
q = queue.Queue()
for h in hosts:
    q.put(h)
out, lock = [], threading.Lock()
log = open(W / "edu_probe2.log", "w")


def worker():
    while True:
        try:
            h = q.get_nowait()
        except queue.Empty:
            return
        url = f"https://{h}/campus"
        body, code = "", "ERR"
        try:
            p = subprocess.run(["curl", "-s", "-L", "-A", UA, "--max-time", "12",
                                "-w", "\n__CODE__%{http_code}", url],
                               capture_output=True, text=True, timeout=20)
            raw = p.stdout
            if "__CODE__" in raw:
                body, code = raw.rsplit("\n__CODE__", 1)
            else:
                body = raw
        except Exception:
            pass
        n = len(set(re.findall(r"/campus/view/id/(\d+)", body)))
        rec = {"host": h, "code": code, "items": n, "len": len(body),
               "title": re.search(r"<title>(.*?)</title>", body, re.S).group(1).strip()[:40]
               if re.search(r"<title>(.*?)</title>", body, re.S) else ""}
        with lock:
            out.append(rec)
            log.write(json.dumps(rec, ensure_ascii=False) + "\n")
            log.flush()
            if n > 0 or code == "200":
                print(rec, flush=True)
        time.sleep(1.0)


ths = [threading.Thread(target=worker) for _ in range(8)]
[t.start() for t in ths]
[t.join() for t in ths]
(W / "edu_probe2.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print("done", len(out), "200:", sum(1 for r in out if r["code"] == "200"),
      "items:", sum(1 for r in out if r["items"] > 0))
