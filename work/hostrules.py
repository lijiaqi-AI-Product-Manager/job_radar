"""共享的「域名归属与黑名单」规则。

放在一处，是为了让 merge / navigate / audit / build 各阶段用同一套判据，
避免出现「上游放过、下游又杀」或「上游杀掉、下游又救回」的来回震荡。

三条判据，按优先级：
1. AGGREGATOR —— 招聘中介/聚合站/内容农场/应用商店。作为**入口**一律不要：
   它不是这家公司的官方招聘站，链接会失效、内容会被替换、也违反「不抄第三方日历」。
2. MEDIA —— 媒体门户（www.163.com 这类）。拒绝门户主体，但**放行其招聘子域**
   （campus.163.com / jobs.bytedance.com / careers.ctrip.com 都是官方站）。
3. ATS —— 第三方 ATS 平台（北森/大易/飞书/Workday…）。这是合法入口，
   公司把招聘站托管在 ATS 上是常态，不算第三方聚合。
"""

import re

# 招聘中介 / 聚合 / 内容农场 / 应用商店 / 文档站 —— 作为入口一律不要
AGGREGATOR = re.compile(
    r"(niuqizp|upcv\.tech|fenbi\.com/page|qiuzhaowang|jrzp\.com|"
    # 智联招聘：只有 zhaopin.com / *.zhaopin.com 是平台。
    # 大量央企自建的是 zhaopin.<自家域名>（zhaopin.chinacoal.com），必须放行。
    r"(?:^|\.)zhaopin\.(?:com|cn)$|"
    r"(?:^|\.)51job\.com|(?:^|\.)liepin\.com|"
    r"(?:^|\.)zhipin\.com|nowcoder|kanzhun|yingjiesheng\.com|shixiseng|jobui\.com|"
    r"(?:^|\.)dajie\.com|chinahr\.com|"
    r"gaoxiaojob|gxrc|ejob\.|chinajob|offcn|gwy\.com|zhaopinbao|liebiao|hahazhao|"
    r"ykof\.|gxbys|deizao|uhouzz|zhaopinhu|chinacareer|jobcn|(?:^|\.)myjob|ganji|58\.com|"
    r"kdocs\.cn|docin\.com|doc88\.com|renrendoc\.com|360doc\.com|"
    r"itunes\.apple|play\.google|appdetail|^apps\.|"
    # 2026-10-26 实测抓到的校招信息中介/内容农场（会把公司公告搬走再卖流量）
    r"shanganclaw|15386\.cn|hicv\.cn|zhidianmijin|shangan|offerdown|qiuzhibang|"
    r"zhaopinhui|campusjob|jobxiaozhao|"
    r"jiemian\.com|huxiu\.com|tmtpost\.com|"
    # 2026-10-26 实测漏网：offernotes.cn 把各家校招公告二次聚合后当投递页发布。
    # 它既不是公司官方入口，也没有转载授权，绝不能当成 apply_url 出现在日历里。
    r"offernotes|offershow|shixiseng|maimai\.cn)", re.I)

# 媒体门户：只拒门户主体（www./m./news.），不连坐招聘子域
MEDIA = re.compile(
    r"^(?:m|www|wap|news|ent|sports|tech|finance|money|auto|house|edu|games?|mil|astro|book|"
    r"reads|health|baby|diy|travel|fashion|digi|it|home|cul|gd|view|comment|blog|video|photo|"
    r"pic|slide|topic|special|zt|live|v|f|t|k)\.(?:sohu|sina|163|qq|ifeng|thepaper|toutiao|baidu)"
    r"\.(?:com|cn|com\.cn)$", re.I)

# 第三方 ATS：合法入口
ATS_HOSTS = (
    "zhiye.com", "hotjob.cn", "mokahr.com", "myworkdayjobs.com", "myworkday.cn", "feishu.cn",
    "f.mioffice.cn", "italent.cn", "dayee.com", "hcmcloud.cn", "beisen.com", "knx.com.cn",
    "career.site", "hire.163.com", "jobs.feishu.cn", "italent.cn", "mokahr.com",
)

# 高校就业网 / 政府就业平台：可以作为**字段证据来源**，但不能当公司入口
GOV_EDU = re.compile(r"(\.edu\.cn$|\.edu$|\.gov\.cn$|ncss\.cn|chsi\.com\.cn|iguopin\.com)", re.I)


def host_of(url: str) -> str:
    m = re.match(r"^https?://([^/]+)", url or "", re.I)
    return (m.group(1) if m else "").lower()


def is_ats(url: str) -> bool:
    h = host_of(url)
    return any(h.endswith(a) or h == a for a in ATS_HOSTS)


def is_aggregator(url: str) -> bool:
    """只对**主机名**做匹配。

    绝不要把整条 URL 丢进去：`job.ceair.com/campus/campusJobList.html` 里的
    路径片段 `campusJob` 会误命中介规则，把东航自己的招聘站判成聚合站。
    """
    return bool(AGGREGATOR.search(host_of(url)))


def is_media(url: str) -> bool:
    return bool(MEDIA.search(host_of(url)))


def usable_as_entry(url: str) -> bool:
    """这个 URL 能不能当「公司的投递入口」。"""
    if not url:
        return False
    if is_aggregator(url) or is_media(url):
        return False
    if GOV_EDU.search(host_of(url)):
        return False
    return True
