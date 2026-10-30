"""抓取前的 robots.txt 合规检查。

为什么单独有这一层：2026-10-26 一天之内踩到两次同类问题 ——

  1. **radancy（欧莱雅）**：robots 是逐条 `Disallow` 前缀，我只看了第一条
     `/search-jobs`，就用 `/en/location/china-mainland-jobs/…` 抓了 351 个岗位。
     回头读全文才发现 `/location/` 也在禁止列表里。
  2. **tupu360（共享域名）**：`careersite.tupu360.com` 上探到 6 个租户、774 个岗位，
     适配器全部解析成功，结果这个主机的 robots 是一行 `Disallow: /`。

两次的共同点是「适配器跑通了、`opened: 41`，但根本不允许抓」。所以判断「能不能抓」
必须独立于「能不能解析」，而且要在**写源配置之前**做。

用法（只在诊断命令里调，不进 crawl 主流程 —— 那会把每轮抓取变成 N 次额外请求）：

    PYTHONPATH=src python3 -m jobradar.cli doctor --robots
"""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from jobradar.adapters.base import USER_AGENT

# 这些路径前缀用来判断「该主机的**列表/详情页**是否被禁」。源配置里 params 的
# base + tenant/path 拼出来的实际 URL 会逐个过一遍。
PROBE_TIMEOUT = 10.0


@dataclass
class RobotsVerdict:
    url: str
    host_robots: str      # present / absent（404/410）/ unavailable（其它4xx）/ unreachable（网络/5xx/挑战）
    allowed: bool
    reason: str

    def __str__(self) -> str:
        return f"{self.url} -> {'OK' if self.allowed else 'BLOCKED'}（{self.reason}）"


def fetch_robots(client: httpx.Client, url: str) -> tuple[str, list[str]]:
    """返回规则状态；RFC 9309 区分 4xx 规则不可用与网络/5xx 不可达。

    只认「整个主机全禁」这一种强信号；逐条前缀交给 `allows()` 判断 —— 因为
    `Disallow: /search-jobs` 这种前缀禁，`urls_allowed` 才能算准。这里不做判断。
    """
    parts = urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        r = client.get(robots_url, headers={"User-Agent": USER_AGENT}, follow_redirects=True,
                       extensions={"jobradar_robots_probe": True}, timeout=PROBE_TIMEOUT)
    except httpx.HTTPError:
        return "unreachable", []
    if r.status_code in (404, 410):
        return "absent", []
    if 400 <= r.status_code < 500 and r.status_code != 429:
        # 仅指 robots 文件不可用，不是对岗位内容的授权；岗位的 401/403 仍按正常错误停止。
        return "unavailable", [f"# robots.txt HTTP {r.status_code}; RFC 9309 section 2.3.1.3"]
    if r.status_code == 204:
        return "present", []
    if r.status_code != 200 or "html" in r.headers.get("content-type", "").lower():
        return "unreachable", []
    if re.search(r"<(?:!doctype|html|script|textarea)\b", r.text, re.I):
        return "unreachable", []
    lines = r.text.splitlines()
    meaningful = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if meaningful and not any(re.match(r"(?:user-agent|sitemap)\s*:", line, re.I) for line in meaningful):
        return "unreachable", []
    return "present", lines


_LANG = {"en", "zh", "cn", "fr", "de", "ja", "ko", "es", "pt", "ru", "it"}


def _path_variants(path: str) -> list[str]:
    """路径本身 + 去掉语言段的版本，用于「保守匹配」。

    `/en/location/china-mainland-jobs/...` -> 也拿 `/location/china-mainland-jobs/...` 去比，
    这样 `Disallow: /location/` 能命中（站点意图明确禁掉整个栏目，不分语言）。
    """
    out = [path]
    segs = path.split("/")
    if len(segs) > 2 and segs[1].lower() in _LANG:
        out.append("/" + "/".join(segs[2:]))
    return out


def _decision(lines: list[str], url: str) -> tuple[bool, str | None]:
    parts = urlsplit(url)
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"

    agents: list[str] = []
    rules_started = False
    product = USER_AGENT.split("/", 1)[0].lower()
    best: tuple[int, bool, str] | None = None
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if rules_started:
                agents = []
                rules_started = False
            agents.append(value.lower())
            continue
        rules_started = True
        if not any(agent in ("*", product) for agent in agents) or key not in ("allow", "disallow"):
            continue
        if not value:
            continue
        anchored = value.endswith("$")
        pattern = value[:-1] if anchored else value
        regex = "^" + re.escape(pattern).replace(r"\*", ".*") + ("$" if anchored else "")
        for probe in _path_variants(path):
            if re.search(regex, probe):
                cand = (len(pattern.replace("*", "").encode("utf-8")), key == "allow", value)
                if best is None or cand[0] > best[0] or (cand[0] == best[0] and cand[1]):
                    best = cand
                break
    if best is None:
        return True, None
    return best[1], best[2]


def allows(lines: list[str], url: str) -> bool:
    """最长规则、Allow 同长优先；支持 *、$、同组多个 UA 与保守的语言路径归一。

    与原有规则一致，通配组和本项目具名组均核查，避免利用语言段绕过明确的栏目禁令。
    """
    return _decision(lines, url)[0]


def check(client: httpx.Client, url: str) -> RobotsVerdict:
    """检查一个具体 URL 是否可抓。"""
    status, lines = fetch_robots(client, url)
    if status == "absent":
        return RobotsVerdict(url, "absent", True, "robots.txt 404/410，无规则可依")
    if status == "unreachable":
        return RobotsVerdict(url, status, False, "robots.txt 无法核实（网络错误、拒绝或挑战页），暂停访问")
    if status == "unavailable":
        return RobotsVerdict(url, status, True, "robots.txt HTTP 4xx，按 RFC 9309 无适用规则；不代表内容使用授权")
    allowed, hit = _decision(lines, url)
    if not allowed:
        return RobotsVerdict(url, "present", False, f"命中 Disallow: {hit}")
    return RobotsVerdict(url, "present", True, "robots 有规则但本路径未被禁")


# 自研站的主机写死在适配器常量里（params 为空），只在这里登记一份用于 robots 检查。
# 新增自研站适配器时**必须**同步加到这里，否则 `doctor --robots` 会漏检。
_HARDCODED_HOSTS: dict[str, list[str]] = {
    "alibaba": ["https://campus-talent.alibaba.com/"],
    "baidu": ["https://talent.baidu.com/"],
    "bytedance": ["https://jobs.bytedance.com/"],
    "jd": ["https://campus.jd.com/"],
    "meituan": ["https://zhaopin.meituan.com/"],
    "netease": ["https://campus.163.com/", "https://campus.game.163.com/"],
    "tencent": ["https://join.qq.com/"],
    "tencent_campus": ["https://join.qq.com/"],
    "nio": ["https://nio.jobs.feishu.cn/"],
    "xpeng": ["https://xiaopeng.jobs.feishu.cn/"],
    "momenta": ["https://momenta.jobs.feishu.cn/"],
}


def source_urls(params: dict, adapter: str = "") -> list[str]:
    """从这个源实际会请求的入口，推断出需要检查 robots 的 URL。

    按 adapter 分派而不是瞎猜 —— 每种平台的主机拼法都不一样（2026-10-26 实测）：

      beisen         {tenant}.zhiye.com/api/Jobad/GetJobAdPageList   （tenant 自己就是主机前缀）
      beisen_legacy  {host} 或 {tenant}.zhiye.com
      hotjob         {host}（params 里直接给全域名）
      tupu360        {base}/{tenant}/position/index
      radancy        {base}/{path 或 lang/search-jobs/country}
      workday        https://{host}/wday/cxs/...
      moka 等自研站    params 里通常有 base/url

    推断不出来就返回空列表（CLI 会标 UNKNOWN 交人工），**不要**瞎补一个域名 ——
    检查一个错的 URL 得出的「允许」比不检查更危险。
    """
    def _s(key: str) -> str:
        return str(params.get(key) or "").strip().rstrip("/")

    base = _s("base") or _s("base_url") or _s("url") or _s("origin")
    tenant = _s("tenant")
    host = _s("host")
    if not host and adapter == "hotjob":
        # hotjob 适配器的 DEFAULT_HOST；源配置只有给了自定义域名才写 host
        host = "wecruit.hotjob.cn"
    out: list[str] = []

    # 只有北森把 tenant 当主机前缀用；其它平台的 tenant 是**路径段**，不能拼进主机名。
    if adapter in ("beisen", "beisen_legacy"):
        if tenant:
            out.append(f"https://{tenant}.zhiye.com/api/Jobad/GetJobAdPageList")
            out.append(f"https://{tenant}.zhiye.com/")
    if host:
        # hotjob/workday 的 host 已经是完整域名（ausnutria.hotjob.cn / nvidia.wd5.myworkdayjobs.com）
        out.append(host if host.startswith("http") else f"https://{host}/")
    if base:
        if tenant:
            out.append(f"{base}/{tenant}/position/index")              # tupu360
            out.append(f"{base}/{tenant}/position/positionTotal")
        if params.get("path"):
            out.append(f"{base}/{_s('path').replace('{page}', '1')}")  # radancy path 模式
        else:
            lang = _s("lang")
            country = _s("country")
            seg = "/".join(x for x in (lang, "search-jobs", country) if x)
            if adapter == "radancy" or country:
                out.append(f"{base}/{seg}" if seg else f"{base}/search-jobs")
            elif not tenant:
                out.append(f"{base}/")
    # 自研站（alibaba/baidu/bytedance/jd/meituan/tencent/netease）把主机写死在适配器里，
    # params 是空的。这里按 adapter 补上各自的列表入口，只用于 robots 检查。
    out.extend(_HARDCODED_HOSTS.get(adapter, []))
    # 去重保序
    seen: set[str] = set()
    uniq = []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq
