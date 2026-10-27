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
    host_robots: str      # "allow" / "deny" / "absent"（404 或不是文本）
    allowed: bool
    reason: str

    def __str__(self) -> str:
        return f"{self.url} -> {'OK' if self.allowed else 'BLOCKED'}（{self.reason}）"


def fetch_robots(client: httpx.Client, url: str) -> tuple[str, list[str]]:
    """返回 (状态, 规则行)。状态：allow（无规则/全允许）/ deny（Disallow: /）/ absent（404）。

    只认「整个主机全禁」这一种强信号；逐条前缀交给 `allows()` 判断 —— 因为
    `Disallow: /search-jobs` 这种前缀禁，`urls_allowed` 才能算准。这里不做判断。
    """
    parts = urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        r = client.get(robots_url, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    except httpx.HTTPError:
        return "absent", []
    if r.status_code != 200 or "html" in r.headers.get("content-type", ""):
        # 404 或返回 HTML（nginx 默认错误页）：没有 robots 规则可依
        return "absent", []
    lines = r.text.splitlines()
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


def allows(lines: list[str], url: str) -> bool:
    """按 robots 规则判断单个 URL 是否允许。

    自己实现而不是 `urllib.robotparser.RobotFileParser`：标准库会把 `User-agent: *` 与
    具名 agent 规则合并得比较粗糙，而且我们需要**知道是哪条规则拒的**（写进报告）。

    **比字面规范更保守一点**：除了标准的前缀匹配，还额外检查「规则去掉前导/内嵌语言段后
    是否仍是前缀」。原因是欧莱雅这类站点写 `Disallow: /location/`，而英文页实际是
    `/en/location/…` —— 按字面不匹配（标准库 `can_fetch` 也返回 True），但站点意图非常明确。
    2026-10-26 就是因为抓着这条字面缝隙抓了 351 个岗位。宁可少抓。
    """
    parts = urlsplit(url)
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"

    applies = False       # 当前规则块是否适用 `*`
    best: tuple[int, bool] | None = None   # (规则长度, 是否允许)，取最长匹配
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            # `*` 或我们的 UA 都算适用；其它 agent 开始新块，停止适用
            applies = value == "*" or "jobradar" in value.lower()
            continue
        if not applies or key not in ("allow", "disallow"):
            continue
        if not value:
            continue
        # `Disallow: /search-jobs` 是前缀匹配（robots 规范如此，不是 glob）
        for probe in _path_variants(path):
            if probe.startswith(value):
                cand = (len(value), key == "allow")
                if best is None or cand[0] > best[0] or (cand[0] == best[0] and cand[1]):
                    best = cand
                break
    if best is None:
        return True
    return best[1]


def check(client: httpx.Client, url: str) -> RobotsVerdict:
    """检查一个具体 URL 是否可抓。"""
    status, lines = fetch_robots(client, url)
    if status == "absent":
        return RobotsVerdict(url, "absent", True, "robots.txt 404/非文本，无规则可依")
    if not allows(lines, url):
        # 找出拒它的那条规则，写进 reason，方便人工复核
        parts = urlsplit(url)
        path = parts.path or "/"
        hit = next(
            (v for k, v in (
                (ln.split(":", 1)[0].strip().lower(), ln.split(":", 1)[1].strip())
                for ln in lines if ":" in ln
            ) if k == "disallow" and v and path.startswith(v)),
            "?",
        )
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
