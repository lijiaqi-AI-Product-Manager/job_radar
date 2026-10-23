# 发布到 PyPI

目标：让用户一条命令装上——`pip install jobradar`。

项目名 `jobradar` 在 PyPI 上**当前可用**（2026-10-24 查询 404；注意 `job-radar` 是另一个项目，不要混淆）。

## 一次性配置（需要仓库所有者操作，约 5 分钟）

1. 注册/登录 <https://pypi.org>，进入 **Account settings → Publishing → Add a new pending publisher**
2. 按下表填（这是 Trusted Publishing，之后不需要在仓库里存任何 token）：

| 字段 | 值 |
|---|---|
| PyPI Project Name | `jobradar` |
| Owner | `lijiaqimun-coder` |
| Repository name | `job_radar` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

3. 到 GitHub 仓库 **Settings → Environments** 新建两个环境：`pypi`、`testpypi`（可只对 tag 设保护）

配置完成后，工作流 `publish-pypi` 就能用 OIDC 身份直接发布，仓库里不需要任何 PyPI 密钥。

## 发一个版本

```bash
# 1) 改版本号（两处必须一致）
#    pyproject.toml: version = "1.0.1"
#    uv.lock 由 uv 自动更新
uv lock

# 2) 更新 CHANGELOG（把 Unreleased 段落改成 [1.0.1] - 日期）

# 3) 本地自检
uv run pytest && uv run ruff check src tests scripts
uv run python scripts/release_check.py --home ~/.jobradar

# 4) 提交 + 打 tag + 推（tag 会触发 publish-pypi）
git add -A && git commit -m "release: 1.0.1"
git tag v1.0.1 && git push origin main --tags

# 5) 验证
pip install -U jobradar && jobradar --version
```

## 预演（TestPyPI）

GitHub → Actions → **publish-pypi** → Run workflow → `target` 选 `testpypi`。
装预演版本：`pip install -i https://test.pypi.org/simple/ jobradar`。

## 发布了什么

- wheel（`jobradar-<ver>-py3-none-any.whl`）+ sdist
- 只包含 `src/jobradar` + 少量数据文件（sources/taxonomy/targets/calendar/skill/docs），
  **不含**任何 `*.db`、缓存或密钥；CI 会检查产物 < 5MB
- 数据本体不走 PyPI，仍由 `jobradar update` 从 Release / Gitee 下载（PyPI 有单文件大小限制）

## 常见问题

- **`invalid-publisher`**：PyPI 上的 pending publisher 和实际 workflow 文件/环境名对不上，逐字段核对上表
- **`File already exists`**：PyPI 不允许覆盖已发布版本，必须升版本号
- **想撤回**：PyPI 允许 yank（不删），`pip install` 默认会跳过 yanked 版本
