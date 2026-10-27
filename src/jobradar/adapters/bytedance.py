"""字节跳动校园招聘（`jobs.bytedance.com`）—— 飞书招聘 ATSX 门户的一个实例。

真正的取数逻辑在 `jobradar.adapters.feishu_atsx`（蔚来 / 小鹏 / Momenta / 月之暗面用的是
同一套匿名接口，只有域名和 `website-path` 不同）。这里只保留：
  - `id = "bytedance"`：`sources/bytedance.yaml` 以及历史数据里都按这个 id 引用；
  - 默认 `base_url` / `website_path` / 岗位详情 URL 形状；
  - 模块级函数别名（`recruit_type_of` / `cities_of` / `publish_date`），
    老测试和历史脚本都从这里 import，不用改。
"""

from jobradar.adapters.base import register
from jobradar.adapters.feishu_atsx import (  # noqa: F401  (模块级别名，供外部 import)
    DEFAULT_BASE,
    PAGE_SIZE,
    PORTAL_TYPE,
    FeishuAtsxAdapter,
    cities_of,
    publish_date,
    recruit_type_of,
)

BASE_URL = DEFAULT_BASE
CSRF_URL = f"{BASE_URL}/api/v1/csrf/token"
LIST_URL = f"{BASE_URL}/api/v1/search/job/posts"
JOB_URL = BASE_URL + "/campus/position/{id}/detail"


@register
class BytedanceAdapter(FeishuAtsxAdapter):
    """字节跳动校招站。除 id 与默认门户地址外，与通用 ATSX 适配器完全一致。"""

    id = "bytedance"

    @property
    def base_url(self) -> str:
        return (self.source.params.get("base_url") or BASE_URL).rstrip("/")

    @property
    def website_path(self) -> str:
        return (self.source.params.get("website_path") or "campus").strip("/") or "campus"

    def job_url(self, jid: str) -> str:
        tpl = self.source.params.get("job_url")
        if tpl:
            return str(tpl).format(base=self.base_url, website_path=self.website_path, id=jid)
        return JOB_URL.format(id=jid)


__all__ = [
    "BASE_URL",
    "CSRF_URL",
    "JOB_URL",
    "LIST_URL",
    "PAGE_SIZE",
    "PORTAL_TYPE",
    "BytedanceAdapter",
    "cities_of",
    "publish_date",
    "recruit_type_of",
]
