"""侦察探针：按清单逐条发请求（间隔 ≥1.5s），每个站点先读 robots.txt。只读、低频。
用于侦察接口形态，以及验证"从 GitHub Actions 能否访问目标站点"。

用法：
  python scripts/recon_probe.py --file docs/recon/probe.txt [--body 3000]

清单每行一条（# 开头为注释）：
  GET  <url>                  HTML 只打印标题/脚本地址/疑似接口路径/内嵌 JSON 片段；JSON 打印正文开头
  POST <url> <json body>
  GREP <url> <正则>           打印正则的去重匹配（用于在 JS 包里找接口）
  POSTGREP <url> <json> <正则>  POST 后对响应做正则匹配（json 内不能有空格）
  FORMGREP <url> <a=1&b=2> <正则> 以表单（application/x-www-form-urlencoded）POST 后做正则匹配
  FLOW {json}                 匿名会话（CLAUDE.md 铁律 1）：先 GET 公开页面 page（保留站点下发的 cookie），
                              可从页面取匿名 token（token: {"re": 带一个分组的正则, "header"|"json"|"query": 名字}），
                              可把某个 cookie 回填到请求头（cookie_header: {"cookie": 名, "header": 名}），
                              再按 method/url/json/data/headers 请求接口，grep 可选。只打印 cookie 名与 token 长度，不打印值。
  RENDER <url> [正则]          浏览器渲染（Playwright，CLAUDE.md 铁律 6）：打印页面可见文字（或正则匹配）、
                              页面发出的 XHR/fetch 请求；出现验证码字样时提示停止。
"""

import argparse
import json
import re
import sys
import time
from urllib.parse import parse_qsl, urlsplit

import httpx

UA = "jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; recon probe)"
API_LIKE = re.compile(r"""["'`]((?:https?:)?/{1,2}[\w.\-]*/?[\w\-/.]*(?:api|portal|recruit|job|position|campus)[\w\-/.]*)["'`]""", re.I)
SCRIPT_SRC = re.compile(r"""<script[^>]+src=["']([^"']+)["']""", re.I)
INLINE_JSON = re.compile(r"""(window\.__[\w]+__\s*=|<script[^>]+type=["'](?:application|text)/json["'][^>]*>)""", re.I)


CAPTCHA_HINT = re.compile(r"验证码|滑块|安全验证|captcha|人机验证|请登录|登录后查看", re.I)


def parse_lines(lines):
    out = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("FLOW "):
            spec = json.loads(line[5:])
            out.append(("FLOW", spec.get("page") or spec["url"], spec))
            continue
        parts = line.split(" ", 2)
        out.append((parts[0], parts[1], parts[2] if len(parts) > 2 else None))
    return out


def uniq(items, n=40):
    seen, out = set(), []
    for i in items:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out[:n]


def report(r: httpx.Response, body_chars: int, regex: str | None):
    ctype = r.headers.get("content-type", "")
    text = r.text
    if regex:
        for m in uniq(re.findall(regex, text), 60):
            print("  MATCH", (m if isinstance(m, str) else " | ".join(m))[:300])
        return
    if "json" in ctype or text.lstrip()[:1] in "{[":
        print("  JSON", text[:body_chars])
        return
    t = re.search(r"<title>(.*?)</title>", text, re.S | re.I)
    print("  TITLE", t.group(1).strip()[:100] if t else "-")
    for s in uniq(SCRIPT_SRC.findall(text), 25):
        print("  SCRIPT", s[:250])
    for a in uniq(API_LIKE.findall(text), 40):
        print("  PATH", a[:250])
    for m in list(INLINE_JSON.finditer(text))[:5]:
        print("  INLINE", text[m.start():m.start() + min(body_chars, 1500)].replace("\n", " "))


def run_flow(spec: dict, headers: dict, body_chars: int) -> None:
    """匿名会话：一个 FLOW 用独立的 client，cookie 只在内存里，结束即丢弃。"""
    with httpx.Client(headers=headers, timeout=20, follow_redirects=True) as c:
        extra_headers = dict(spec.get("headers") or {})
        params, body = {}, spec.get("json")
        if spec.get("page"):
            p = c.get(spec["page"], headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
            print(f"  PAGE {p.status_code} {len(p.content)}B cookies={sorted(c.cookies.keys())}")
            if CAPTCHA_HINT.search(p.text[:200000]):
                print("  WARN page mentions captcha/login keywords")
            tok = spec.get("token")
            if tok:
                m = re.search(tok["re"], p.text)
                print(f"  TOKEN {'found len=' + str(len(m.group(1))) if m else 'NOT FOUND'}")
                if m:
                    if "header" in tok:
                        extra_headers[tok["header"]] = m.group(1)
                    elif "query" in tok:
                        params[tok["query"]] = m.group(1)
                    elif "json" in tok:
                        body = {**(body or {}), tok["json"]: m.group(1)}
            time.sleep(1.5)
        ch = spec.get("cookie_header")
        if ch:
            v = c.cookies.get(ch["cookie"])
            print(f"  COOKIE->HEADER {ch['cookie']}: {'present' if v else 'MISSING'}")
            if v:
                extra_headers[ch["header"]] = v
        method = spec.get("method", "GET")
        r = c.request(method, spec["url"], params=params or None, json=body,
                      data=spec.get("data"), headers=extra_headers)
        print(f"  {method} {spec['url']} -> {r.status_code} | {r.headers.get('content-type', '-')} | {len(r.content)}B")
        report(r, body_chars, spec.get("grep"))


def run_render(url: str, regex: str | None, body_chars: int) -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(user_agent=UA, locale="zh-CN")
        calls = []
        page.on("response", lambda r: calls.append((r.request.method, r.status, r.url))
                if r.request.resource_type in ("xhr", "fetch") else None)
        try:
            page.goto(url, wait_until="networkidle", timeout=45000)
        except Exception as e:  # noqa: BLE001 - 侦察脚本：打印即可
            print(f"  GOTO {type(e).__name__}: {str(e)[:200]}")
        page.wait_for_timeout(3000)
        text = page.inner_text("body") if page.query_selector("body") else ""
        html = page.content()
        print(f"  RENDERED title={page.title()[:80]!r} text={len(text)} chars html={len(html)}B")
        if CAPTCHA_HINT.search(text):
            print("  WARN rendered text mentions captcha/login keywords -> stop if it blocks content")
        for m, st, u in uniq(calls, 40):
            print(f"  XHR {m} {st} {u[:250]}")
        if regex:
            for m in uniq(re.findall(regex, text + "\n" + html), 60):
                print("  MATCH", (m if isinstance(m, str) else " | ".join(m))[:300])
        else:
            print("  TEXT", " ".join(text.split())[:body_chars])
        browser.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--body", type=int, default=3000)
    args = ap.parse_args()
    reqs = parse_lines(open(args.file, encoding="utf-8").read().splitlines())

    headers = {"User-Agent": UA, "Accept": "application/json, text/html;q=0.9, */*;q=0.5"}
    with httpx.Client(headers=headers, timeout=20, follow_redirects=True) as client:
        seen_hosts = set()
        for verb, url, extra in reqs:
            host = "{0.scheme}://{0.netloc}".format(urlsplit(url))
            if host not in seen_hosts:
                seen_hosts.add(host)
                print(f"\n===== {host} =====")
                try:
                    rb = client.get(f"{host}/robots.txt")
                    body = rb.text[:800] if "html" not in rb.headers.get("content-type", "") else "(html, no robots)"
                    print(f"ROBOTS {rb.status_code}: {body}")
                except httpx.HTTPError as e:
                    print(f"ROBOTS ERROR {type(e).__name__}")
                time.sleep(1.5)
            t = time.monotonic()
            if verb in ("FLOW", "RENDER"):
                print(f"\n>>> {verb} {url}")
                try:
                    if verb == "FLOW":
                        run_flow(extra, headers, args.body)
                    else:
                        run_render(url, extra, args.body)
                except Exception as e:  # noqa: BLE001
                    print(f"ERROR {type(e).__name__}: {str(e)[:300]}")
                print(f"  ({time.monotonic() - t:.1f}s)")
                time.sleep(1.5)
                continue
            regex = extra if verb == "GREP" else None
            if verb in ("POSTGREP", "FORMGREP"):
                body, regex = extra.split(" ", 1)
                extra = body
            try:
                if verb in ("POST", "POSTGREP"):
                    r = client.post(url, json=json.loads(extra or "{}"))
                elif verb == "FORMGREP":
                    r = client.post(url, data=dict(parse_qsl(extra, keep_blank_values=True)))
                else:
                    r = client.get(url)
            except httpx.HTTPError as e:
                print(f"\n>>> {verb} {url}\nERROR {type(e).__name__}: {e}")
                time.sleep(1.5)
                continue
            print(f"\n>>> {verb} {url}\n{r.status_code} | {r.headers.get('content-type', '-')} | "
                  f"{len(r.content)}B | {time.monotonic() - t:.1f}s | final={r.url}")
            report(r, args.body, regex)
            time.sleep(1.5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
