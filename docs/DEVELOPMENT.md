# 开发规范

本项目维护可追溯的中国招聘信息索引。采集、归一化、入库与查询分层，优先保持数据来源清楚、历史行为稳定和发布格式兼容。

## 铁律

1. **合规访问。** 只读允许公开访问的页面或接口；遇到账号登录、验证码、请求签名或加密限制时停止，记录 `blocked` 与证据。不使用代理池，不伪造 UA。站点给匿名访客正常下发的 cookie / CSRF 值可以按公开页面的正常顺序使用，但只留在本次抓取内存中，不能落盘或进入 fixtures。每个启用源必须记录 robots、条款与核查日期。遵守适配器基类固定 UA、robots 守卫和每源默认不超过 1 请求 / 秒的限速；同一 origin 共享限制。
2. **迁移不可改写。** `src/jobradar/store/migrations/` 中既有迁移保持原样。变更追加后续编号迁移，登记 schema lock 并补回归测试，不更改旧哈希来绕过守卫。
3. **业务变更先写测试。** 先确认回归用例失败，再实现。修改入库、下架或查询前，读完相关实现与测试。抓取失败、拒收和不完整分页不能冒充成功的空结果。
4. **适配器必须可回放。** 每个注册适配器具有专属测试与脱敏 fixtures。测试不连接真实网络；fixture 体积原则上小于 300 KB，保留正常、缺字段与分页终止样本。
5. **采集流程保持可重复。** 流水线不依赖付费服务或语言模型。归一化使用规则与 `taxonomy/` 映射。公开 JSON 优先于服务端 HTML；确实需要浏览器渲染时，同样执行访问检查、固定 UA 与限速。
6. **查询只有一个实现。** SQL 和业务筛选放在 `src/jobradar/core/queries.py`，CLI 与 MCP 调用该层。
7. **正文与缺失值保持真实。** 采集原始职责和要求，列表缺正文时读取允许访问的详情。不能把导航、页脚或模板当作 JD。契约要求至少 90% 样本有正文。没有明确日期、学历、城市或届次证据时留空，不能用通用 JD 推断覆盖适配器的届次判断。
8. **分清记录类型。** 招聘简章不等于单个职位。官方与聚合来源分别标注；公告展示截止日、企业投递截止日分开存储和验证。

## 目录与职责

| 路径 | 职责 |
| :--- | :--- |
| `sources/` | 启用源、平台参数与 compliance |
| `taxonomy/` | 公司简称、职类、城市等映射 |
| `targets/` | 固定目标池、最小入口证据与当前样本 |
| `src/jobradar/adapters/` | 基类、注册表、站点解析、录制与回放 |
| `src/jobradar/pipeline/` | 归一化、入库、状态事件与日历 |
| `src/jobradar/store/` | SQLite 迁移与 schema 守卫 |
| `src/jobradar/core/queries.py` | CLI / MCP 共用查询实现 |
| `tests/` | 业务回归、适配器契约与 fixtures |
| `docs/recon/` | 访问规则、字段映射与读取证据 |
| `evals/` | 查询行为评测 |

## 新增适配器

1. 按 [侦察模板](recon/TEMPLATE.md) 核实公开入口、robots、条款、分页、字段与归属。没有可读取的公开入口时记录受限原因。
2. 阅读 `adapters/example.py`、专属测试模板和 `tests/test_adapter_contract.py`。
3. 以 `_<id>.py` 创建草稿，在 `sources/` 填写真实配置。
4. 通过 `scripts/record_fixtures.py <source_id> --max-pages 2` 录制最小样本。仅在明确录制局部样本时使用 `--allow-partial`；实际采集必须遍历到可靠终点。
5. 写失败回归用例，断言至少一条真实样本的关键字段、JD、链接，以及缺字段、归属冲突、异常分页的处理。
6. 转正模块并注册，修实现直至专属测试、契约测试和全套检查通过。
7. 更新侦察结论、源计数和 CHANGELOG。一个适配器单独提交，避免混入无关改动。

网络只能通过基类 `request_json` / `request_text`，不自行创建客户端或修改访问守卫。共享索引可以复用，但必须按真实公司归属过滤。实现需要模型或 schema 调整时，先明确兼容影响并准备相应回归。

## 命名与时间

| 对象 | 规则 |
| :--- | :--- |
| 适配器模块与 id | 小写蛇形，专属测试为 `test_<id>.py` |
| 适配器类 | `<Id>Adapter`，使用 `@register` |
| source id | 小写，以连字符分隔；共享平台优先 `<平台>-<租户>` |
| 迁移 | 连续编号的 `NNNN_动词_对象.sql` |
| 时间戳 | UTC，`YYYY-MM-DDTHH:MM:SSZ`；明示中国截止日按业务规则处理 |
| 招聘类型 | `campus` / `intern` / `social` |
| 提交信息 | `adapter(id): ...` / `core: ...` / `schema: ...` / `docs: ...` |

提交描述实际行为、原因与验证，不添加开发工具署名或会话链接。

## 验证与发布

```bash
uv sync --frozen --all-extras
uv run pytest
uv run ruff check .
uv run python scripts/check_docs_links.py
uv run python scripts/check_compliance.py
uv run python scripts/coverage_report.py --json
uv build
```

新增迁移后运行 `scripts/update_schema_lock.py`。公开数据先经 `scripts/export_public_databases.py` 导出，不能把工作库的新 schema 直接推给旧客户端。发布前安装构建出的 wheel 验证 CLI / MCP 与包内公司映射，检查 sdist 小于 5 MiB。真实数据与版本流程见 [发布检查](RELEASE.md)和[PyPI 发布](PUBLISHING.md)。
