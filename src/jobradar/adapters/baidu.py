"""百度招聘 talent.baidu.com（校招 GRADUATE / 实习 INTERN / 社招 SOCIAL）。侦察：docs/recon/baidu.md

接口：`POST https://talent.baidu.com/httservice/getPostListNew?recruitType=GRADUATE&curPage=1&pageSize=10`
      body `{}`（**空对象**）
      -> `{"status":"ok","data":{"total":"159","list":[{...}]}}`

2026-10-26 实测的坑（花了四轮才摸清，前两版适配器都是错的）：

1. **`recruitType` 必须同时出现在 query 和 body 里**。只放 body → `Illegal argument : recruitType`；
   只放 query → `不支持的请求，请核实`。两处都放才 200。
2. **类型名不是直觉上的那几个**：`SOCIAL`(1700) / `INTERN`(535) / `GRADUATE`(159) 有效；
   `CAMPUS` / `SCHOOL` / `TRAINEE` / 小写一律 `Illegal argument`。
   校招叫 `GRADUATE` 而不是 `CAMPUS`——这是最容易踩空的一步。
3. **`curPage` / `pageSize` 必须放在 query 里，放 body 里完全无效**（服务端静默忽略）。
   这一点最坑：body 里写 `curPage: 3` 时服务端照样返回第 1 页的 10 条，**不报错**，
   于是第一版适配器"翻页"了 16 次、每次都拿到同一页，最终只入库 20 条而不是 694 条。
   判别方法：比对第 1 页和第 2 页的首条 postId 是否不同。
4. **`pageSize` 只接受 10**，写 50 会得到 `Illegal argument : pageSize`。
   所以翻页数 = ceil(total/10)，GRADUATE 16 页、INTERN 54 页。
5. **必须带 `Referer`**（`https://talent.baidu.com/jobs/list?recruitType=...`），否则
   `{"status":"no-auth","message":"illegal-visit"}`。只加 `Origin: https://talent.baidu.com`
   也不行——实测只要 Referer 不要 Origin。Referer 是浏览器从列表页跳转时本来就会带的头，
   不是伪造身份，符合 CLAUDE.md 铁律（不伪造 UA、不逆向签名）。
6. 列表一次给全：城市 `workPlace`、职类 `postType`、**发布日期 `publishDate`**、
   职责 `workContent`、要求 `serviceCondition`、招聘项目 `projectType`。不需要逐岗详情。

source.params:
  page_size: 固定 10（服务端只接受这个值，参数留着是为了让"为什么是 10"有出处）
"""

from collections.abc import Iterator

from jobradar.adapters.base import Adapter, SkipRecord, register
from jobradar.models import Job
from jobradar.normalize import batch_from_text, cities_from_text, date_only, grad_year_from_text

LIST_URL = "https://talent.baidu.com/httservice/getPostListNew"
JOB_URL = "https://talent.baidu.com/jobs/detail/{id}?recruitType={rt}"
LIST_PAGE = "https://talent.baidu.com/jobs/list?recruitType={rt}"
# 服务端只接受 pageSize=10，其它值报 `Illegal argument : pageSize`
PAGE_SIZE = 10
# recruitType 就是招聘类型本身，不做二次推断（页面下拉框只有这三项）
RECRUIT_TYPE = {"GRADUATE": "campus", "INTERN": "intern", "SOCIAL": "social"}
TYPE_CODE = {"campus": "GRADUATE", "intern": "INTERN", "social": "SOCIAL"}


@register
class BaiduAdapter(Adapter):
    id = "baidu"

    def _page(self, code: str, page: int, size: int) -> dict:
        # 分页参数必须放在 query 里；放 body 里服务端会**静默忽略**并一直返回第 1 页
        # （不报错，只是每页返回同样的 10 条）。body 里仍要带 recruitType，见模块 docstring 第 1 条。
        url = f"{LIST_URL}?recruitType={code}&curPage={page}&pageSize={size}"
        data = self.request_json(
            "POST", url, json={"recruitType": code},
            headers={"Referer": LIST_PAGE.format(rt=code)},  # 缺 Referer -> illegal-visit，见模块 docstring
        )
        if data.get("status") != "ok":
            raise RuntimeError(f"baidu {code} p{page}: {data.get('message') or data.get('status')}")
        return (data.get("data") or {})

    def fetch_raw(self) -> Iterator[dict]:
        size = PAGE_SIZE
        for rtype in self.source.recruit_types:
            code = TYPE_CODE[rtype]
            page = 1
            seen: set[str] = set()
            while True:
                body = self._page(code, page, size)
                items = body.get("list") or []
                # 空页只结束「当前类型」，不能 return——否则配了多个 recruit_types 时后面的类型一条也抓不到
                if not items:
                    break
                # 自检：分页参数一旦失效，服务端会重复返回同一页。靠 postId 去重让"重复页"变成空转并停下，
                # 避免同一个 bug 静默地把 694 条抓成 20 条（2026-10-26 真实发生过）。
                fresh = [it for it in items if str(it.get("postId")) not in seen]
                if not fresh:
                    break
                for it in fresh:
                    seen.add(str(it.get("postId")))
                    yield {**it, "_recruit_type": rtype, "_code": code}
                try:
                    total = int(body.get("total") or 0)
                except (TypeError, ValueError):
                    total = 0
                if page * size >= total:
                    break
                if self.source.max_pages and page >= self.source.max_pages:
                    break
                page += 1

    def normalize(self, raw: dict) -> Job:
        post_id = raw.get("postId")
        title = (raw.get("name") or "").strip()
        if not post_id or not title:
            raise SkipRecord
        rtype = raw["_recruit_type"]
        cities: list[str] = []
        for c in cities_from_text(raw.get("workPlace")):
            if c not in cities:
                cities.append(c)
        project = (raw.get("projectType") or "").strip()
        return Job(
            source_id=self.source.id,
            source_job_id=str(post_id),
            company=self.source.company,
            url=JOB_URL.format(id=post_id, rt=raw["_code"]),
            title=title,
            recruit_type=rtype,
            # 届别只看标题/项目名里明写的（"2027届"/"2027"），不猜
            grad_year=grad_year_from_text(title) or grad_year_from_text(project) if rtype != "social" else None,
            batch=batch_from_text(project) or batch_from_text(title) if rtype == "campus" else None,
            cities=cities,
            department=(raw.get("orgName") or "").strip() or None,
            # 列表直接给 publishDate（YYYY-MM-DD）；updateDate 是"最近更新"，不当上架日
            publish_at=date_only(raw.get("publishDate")),
            description=(raw.get("workContent") or "").strip() or None,
            requirements=(raw.get("serviceCondition") or "").strip() or None,
        )
