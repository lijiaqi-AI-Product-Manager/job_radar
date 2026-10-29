"""Nuxt 服务端载荷（`window.__NUXT__=`）的纯 Python 解析。

为什么需要它：实习僧等 Nuxt 站点把整页数据塞进一段压缩过的 JS 表达式，
形如 `(function(a,b,...,Z){return {布局...}}(实参...))`，字段值大量是指向
函数形参的标识符（`cname:e`），直接正则拿不到真名。执行 JS 要装 node 子进程，
本项目不引入这种运行时依赖，所以这里做**最小的**求值：只解析字面量与标识符
回填，不做运算、不调用函数。

两种形态都要支持：
1. 返回式（列表页）：`(function(a,b){return {...}}(x,y))`      -> `eval_returning()`
2. 语句式（详情页/公司页）：`(function(a){i.x=1;i.y="z";}(x))`  -> `eval_assignments()`

不是通用 JS 解释器：遇到真表达式一律抛 `NuxtParseError`，宁可解析失败也不静默
产出错误数据——这个数据集的全部价值建立在"字段是真实的"之上。
"""

from __future__ import annotations

import json
import re

_PARAM = re.compile(r"\(?\s*function\s*\(([^)]*)\)\s*\{")
_ASSIGN = re.compile(r"\.([A-Za-z_$][\w$]*)=(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|!0|!1|void 0|null|-?\d+(?:\.\d+)?|[A-Za-z_$][\w$]*)")


class NuxtParseError(ValueError):
    """载荷结构不是可识别的 Nuxt 压缩格式（多半是站点改版或被拦了）。"""


class _Raw(str):
    """没能解析出来的标识符/表达式。保留原文便于报错定位。"""


def split_top(s: str, sep: str = ",") -> list[str]:
    """按顶层分隔符切分，跳过字符串与括号内部。"""
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    i, n = 0, len(s)
    quote = ""
    while i < n:
        ch = s[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and i + 1 < n:
                buf.append(s[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'":
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


def _js_string(body: str) -> str:
    """JS 字符串字面量的内容（已去引号）-> Python str。"""
    try:
        return json.loads('"' + body + '"')
    except ValueError:
        return (body.replace("\\u002F", "/").replace("\\u002f", "/")
                .replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\"))


def parse_literal(tok: str):
    """解析一个 JS 字面量；认不出来时返回 `_Raw(原文)`。"""
    tok = tok.strip()
    if not tok:
        return _Raw(tok)
    if tok in ("void 0", "undefined", "null"):
        return None
    if tok == "!0":
        return True
    if tok == "!1":
        return False
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'":
        return _js_string(tok[1:-1])
    if tok[0] == "[" and tok[-1] == "]":
        return [parse_literal(x) for x in split_top(tok[1:-1])]
    if tok[0] == "{" and tok[-1] == "}":
        obj: dict = {}
        for part in split_top(tok[1:-1]):
            k, sep, v = part.partition(":")
            if sep:
                obj[k.strip().strip("\"'")] = parse_literal(v)
        return obj
    if re.fullmatch(r"-?\d+(\.\d+)?", tok):
        return float(tok) if "." in tok else int(tok)
    return _Raw(tok)


def _expr(html: str) -> str:
    i = html.find("__NUXT__=")
    if i < 0:
        raise NuxtParseError("页面里没有 __NUXT__（可能被反爬页/登录页替换了）")
    j = html.find("</script>", i)
    return html[i + len("__NUXT__="): j if j > 0 else len(html)].strip().rstrip(";")


def _unwrap_outer(expr: str) -> str:
    """去掉最外层包住整个 IIFE 的括号：(function…(a)) -> function…(a)。"""
    s = expr.strip()
    while s.startswith("(") and s.endswith(")"):
        depth, quote, ok = 0, "", True
        for i, ch in enumerate(s):
            if quote:
                if ch == "\\":
                    continue
                if ch == quote:
                    quote = ""
                continue
            if ch in "\"'":
                quote = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i != len(s) - 1:
                    ok = False  # 外层括号在中间就闭合了，这一层不是包装层
                    break
        if not ok:
            break
        s = s[1:-1].strip()
    return s


def _split_body(expr: str) -> tuple[list[str], str, list[str]]:
    """-> (形参, 函数体, 实参)。函数体是 `{` 与配对 `}` 之间的原文。"""
    s = _unwrap_outer(expr)
    m = _PARAM.match(s)
    if not m:
        raise NuxtParseError("找不到 function(...){")
    params = [p.strip() for p in m.group(1).split(",") if p.strip()]
    start = m.end() - 1  # 指向函数体的 {
    depth, i, n, quote, end = 0, start, len(s), "", -1
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
                end = i
                break
        i += 1
    if end < 0:
        raise NuxtParseError("函数体没有闭合")
    body = s[start + 1:end]
    rest = s[end + 1:].strip()
    if rest.startswith("(") and rest.endswith(")"):
        args = split_top(rest[1:-1])
    elif not rest:
        args = []
    else:
        raise NuxtParseError("函数体之后不是 (实参)")
    return params, body, args


def _signature_and_args(expr: str) -> tuple[list[str], list[str]]:
    params, _, args = _split_body(expr)
    return params, args


def _env(expr: str) -> dict:
    params, args = _signature_and_args(expr)
    if len(params) != len(args):
        raise NuxtParseError(f"形参 {len(params)} 个、实参 {len(args)} 个，不匹配")
    return {p: parse_literal(a) for p, a in zip(params, args, strict=True)}


def resolve(tok: str, env: dict):
    """字面量直接返回；标识符按 env 回填。"""
    val = parse_literal(tok)
    if isinstance(val, _Raw):
        return env.get(tok.strip())
    return val


def eval_returning(html: str) -> dict:
    """返回式载荷 -> 顶层 dict（值里的标识符已回填）。"""
    expr = _expr(html)
    params, body, args = _split_body(expr)
    if len(params) != len(args):
        raise NuxtParseError(f"形参 {len(params)} 个、实参 {len(args)} 个，不匹配")
    env = {p: parse_literal(a) for p, a in zip(params, args, strict=True)}
    body = body.strip()
    if not body.startswith("return "):
        raise NuxtParseError("这是语句式载荷，请用 eval_assignments()")
    obj = parse_literal(body[len("return "):].strip())
    if isinstance(obj, _Raw):
        raise NuxtParseError("return 之后不是可解析的对象字面量")

    def fill(v):
        if isinstance(v, _Raw):
            return env.get(str(v))
        if isinstance(v, list):
            return [fill(x) for x in v]
        if isinstance(v, dict):
            return {k: fill(x) for k, x in v.items()}
        return v

    return fill(obj)


def eval_assignments(html: str, keys: tuple[str, ...] | None = None) -> dict:
    """语句式载荷 -> {字段名: 值}。只取 `x.field=字面量` 形式的赋值。

    站点把每个岗位存成 `i.iname="..."`、`i.info="..."` 这种逐字段赋值，
    `keys` 给了就只解析这些字段（省掉整页解析开销）。
    """
    expr = _expr(html)
    env = _env(expr)
    out: dict = {}
    for key, tok in _ASSIGN.findall(expr):
        if keys is not None and key not in keys:
            continue
        out[key] = resolve(tok, env)
    if not out:
        raise NuxtParseError("语句式载荷里没有可识别的字段赋值")
    return out
