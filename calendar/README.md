# 招聘日历

**1,383 个条目文件 · 2,078 条人工整理记录 · 2026-10-31**

包含招聘公司、届次、项目类型、方向、城市、网申时间与原始来源。人工记录与岗位数据生成的日历合并发布，日期缺失保持为空。

抓不到 JD 的公司（验证码/登录墙），以及需要补充批次信息的公司，在这里**人工整理**招聘批次。这是编辑，不是爬虫。
每天由 `jobradar calendar-build` 与数据层自动生成的条目合并成 `calendar.db`，随数据一起发布。

## 红线（`tests/test_calendar.py` 强制检查）

- **来源只用**：公司官方公众号推文（`wechat`，链接须为 mp.weixin.qq.com）、公司官网/官方招聘站公告（`official_site`）、
  教育部 24365 / 国聘 / ncss.cn 等政府平台（`gov`）。
- **不抄第三方日历**：牛客、OfferShow、知乎、小红书笔记等域名会被拒绝（见 `taxonomy/calendar.yaml`）。
- **每条必带来源与时间戳**：`source.name`、`as_of`（核实日）必填；公众号来源必须写推文日期。
- **查不到的不编**：网申起止、城市、方向等，来源没写就留空（`null` / `[]`）。
- **不碰验证码和登录墙**：只引用公开可访问的页面。

## 格式

一个集团一个文件，`group` 必须与 `targets/top_companies.yaml` 中的名字一致：

```yaml
group: 阿里巴巴
entries:
  - id: alibaba-fliggy-2027-qz          # 小写字母/数字/-，全局唯一
    company: 飞猪旅行有限公司             # 具体公司（可空）
    product: 飞猪旅行                     # 具体产品/业务（可空）
    grad_year: 2027                       # 届次
    project_type: 秋招正式批              # 见 taxonomy/calendar.yaml；实习/校招等分条目
    tracks:                               # 方向 + 具体岗位，可多条
      - {direction: 技术类, roles: [算法, 后端, 客户端]}
      - {direction: 产品类, roles: [AI产品]}
    apply_start: 2026-08-03               # 来源写明才填
    apply_end: 2026-12-31
    cities: [北京, 上海, 深圳, 杭州, 成都]
    apply_url: https://talent.alibaba.com/campus/...
    source:
      type: wechat                        # wechat / official_site / gov
      name: 阿里巴巴集团招聘 公众号
      url: https://mp.weixin.qq.com/s/...
      date: 2026-08-03                    # 推文/公告发布日期
    as_of: 2026-10-21                     # 你核实这条信息的日期
    jd: {status: blocked, url: https://talent.alibaba.com/campus}   # official_page（公开 JD 页）/ blocked（被挡）/ none
    notes: 可选备注
```

公司若已在数据层（有可抓取的 JD），条目会自动关联 JD（`jd_status: linked`），不需要手写。
JD 被挡（`blocked`）的条目，查询结果会附上"{公司}希望你去他们的招聘页逛一逛哦~"。
