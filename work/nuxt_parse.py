"""实习僧 Nuxt 载荷的纯 Python 解析（不依赖 node）。

页面形如：
    window.__NUXT__=(function(a,b,c,...,Z){return {layout:"default",data:[{interns:{data:[...],total:448,pageNumber:1}}],...}}(arg1,arg2,...));

字段名/值被压缩成函数参数引用，所以需要：
1. 拆出形参表与实参表；
2. 把实参解析成 Python 值（字符串/数字/布尔/null/数组/对象）；
3. 在正文里按 `键:标识符` 的形式解析标识符。

只解析我们需要的字段，不做通用 JS 求值。
"""

from __future__ import annotations

import json
import re

IDENT = re.compile(r"^[A-Za-z_$][\w$]*$")


class NuxtParseError(ValueError):
    pass


def _split_top(s: str, sep: str = ",") -> list[str]:
    """按顶层分隔符切分，忽略字符串/括号内部。"""
    out, buf, depth, i, n = [], [], 0, 0, len(s)
    quote = ""
    while i < n:
        ch = s[i]
        if quote:
            buf.append(ch)
            if ch == "\\":
                if i + 1 < n:
                    buf.append(s[i + 1])
                    i += 2
                    continue
            elif ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch in "([{":
            depth += 1
            buf.append(ch)
        elif ch in ")]}":
            depth -= 1
            buf.append(ch)
        elif ch == sep and depth == 0:
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def _unescape(js: str) -> str:
    """JS 字符串字面量 -> Python 字符串。"""
    try:
        return json.loads('"' + js + '"')
    except Exception:  # noqa: BLE001
        # 兜底：手工替换常见转义
        return (
            js.replace("\\u002F", "/")
            .replace("\\u002f", "/")
            .replace('\\"', '"')
            .replace("\\n", "\n")
            .replace("\\\\", "\\")
        )


def parse_literal(tok: str):
    """解析一个 JS 字面量，返回 Python 值；无法识别时返回 _Raw。"""
    tok = tok.strip()
    if not tok:
        return _Raw(tok)
    if tok in ("void 0", "undefined", "null"):
        return None
    if tok == "!0":
        return True
    if tok == "!1":
        return False
    if tok[0] == '"' and tok[-1] == '"' and len(tok) >= 2:
        return _unescape(tok[1:-1])
    if tok[0] == "'" and tok[-1] == "'" and len(tok) >= 2:
        return _unescape(tok[1:-1])
    if tok[0] == "[" and tok[-1] == "]":
        return [parse_literal(x) for x in _split_top(tok[1:-1])]
    if tok[0] == "{" and tok[-1] == "}":
        obj = {}
        for part in _split_top(tok[1:-1]):
            k, _, v = part.partition(":")
            key = k.strip().strip("\"'")
            obj[key] = parse_literal(v)
        return obj
    if re.fullmatch(r"-?\d+(\.\d+)?", tok):
        return float(tok) if "." in tok else int(tok)
    return _Raw(tok)


class _Raw(str):
    """未解析出来的标识符/表达式。"""


def split_call(expr: str) -> tuple[list[str], str, list[str]]:
    """`(function(a,b){return BODY}(A,B))` -> (params, body, args)。"""
    s = expr.strip()
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
    m = re.match(r"\(?\s*function\s*\(([^)]*)\)\s*\{\s*return\s", s)
    if not m:
        raise NuxtParseError("找不到 function(...){return")
    params = [p.strip() for p in m.group(1).split(",") if p.strip()]
    body_start = m.end()
    # body 结束于匹配的 `}`，其后紧跟 `(args)`
    depth, i, n = 1, body_start, len(s)
    quote = ""
    while i < n:
        ch = s[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    body = s[body_start:i]
    rest = s[i + 1 :].strip()
    if not rest.startswith("(") or not rest.endswith(")"):
        raise NuxtParseError("return 之后不是 (args)")
    args = _split_top(rest[1:-1])
    return params, body, args


def eval_nuxt(html: str) -> dict:
    i = html.find("__NUXT__=")
    if i < 0:
        raise NuxtParseError("页面里没有 __NUXT__")
    j = html.find("</script>", i)
    expr = html[i + len("__NUXT__=") : j].strip().rstrip(";")
    params, body, args = split_call(expr)
    if len(params) != len(args):
        raise NuxtParseError(f"形参 {len(params)} 个、实参 {len(args)} 个，不匹配")
    env = {p: parse_literal(a) for p, a in zip(params, args, strict=False)}
    return {"body": body, "env": env}


def resolve(token: str, env: dict):
    tok = token.strip()
    v = parse_literal(tok)
    if isinstance(v, _Raw):
        return env.get(tok.strip())
    return v


JOB_ARR = re.compile(r"interns:\{data:\[")


def iter_job_objects(body: str) -> list[str]:
    """取 interns:{data:[ ... ]} 里的每个顶层对象文本。"""
    m = JOB_ARR.search(body)
    if not m:
        return []
    start = m.end() - 1  # 指向 [
    depth, i, n = 0, start, len(body)
    quote = ""
    end = -1
    while i < n:
        ch = body[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                end = i
                break
        i += 1
    if end < 0:
        return []
    return [p for p in _split_top(body[start + 1 : end]) if p.strip()]


FIELD = re.compile(r"(?:^|[{,])\s*([A-Za-z_$][\w$]*)\s*:\s*(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|[A-Za-z_$][\w$]*|-?\d+)")

NEED = ("cname", "name", "city", "uuid", "c_uuid", "minsalary", "maxsalary",
        "degree", "month_num", "day", "refresh")


def parse_jobs(html: str) -> list[dict]:
    data = eval_nuxt(html)
    body, env = data["body"], data["env"]
    total_m = re.search(r"total:(\d+)", body)
    page_m = re.search(r"pageNumber:(\d+)", body)
    jobs = []
    for obj in iter_job_objects(body):
        rec = {}
        for key, tok in FIELD.findall(obj):
            if key in NEED:
                rec[key] = resolve(tok, env)
        if rec.get("uuid"):
            jobs.append(rec)
    return jobs, {
        "total": int(total_m.group(1)) if total_m else len(jobs),
        "page": int(page_m.group(1)) if page_m else 1,
    }


def parse_page(html: str) -> tuple[list[dict], dict]:
    return parse_jobs(html)
