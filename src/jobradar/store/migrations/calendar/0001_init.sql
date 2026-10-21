-- calendar.db：招聘日历（独立于岗位数据）。每日由 `jobradar calendar-build` 从
--   1) calendar/entries/*.yaml（人工编辑，origin='manual'）
--   2) jobs.db 数据层（自动生成，origin='auto'）
-- 合并重建。日期为 YYYY-MM-DD，时间戳为 UTC ISO8601。

CREATE TABLE entry (
    id            TEXT PRIMARY KEY,
    origin        TEXT NOT NULL CHECK (origin IN ('manual', 'auto')),
    group_name    TEXT NOT NULL,                 -- 集团，如 阿里巴巴
    company       TEXT,                          -- 具体公司，如 飞猪旅行有限公司
    product       TEXT,                          -- 具体产品/业务，如 飞猪旅行
    grad_year     INTEGER,                       -- 届次，如 2027
    project_type  TEXT NOT NULL,                 -- 秋招正式批 / 提前批 / 暑期实习 / 社招 …（见 taxonomy/calendar.yaml）
    tracks        TEXT NOT NULL DEFAULT '[]',    -- JSON：[{"direction": "技术类", "roles": ["算法", "后端"]}]
    apply_start   TEXT,                          -- 网申开始（来源写明才填）
    apply_end     TEXT,                          -- 网申截止（来源写明才填）
    observed_from TEXT,                          -- 数据层首次观测到在招（仅 auto）
    observed_to   TEXT,                          -- 数据层最近一次观测到在招（仅 auto）
    cities        TEXT NOT NULL DEFAULT '[]',    -- JSON 数组
    apply_url     TEXT,                          -- 投递入口
    source_type   TEXT NOT NULL CHECK (source_type IN ('wechat', 'official_site', 'gov', 'data_layer')),
    source_name   TEXT NOT NULL,                 -- 如 "字节跳动招聘 公众号"
    source_url    TEXT,
    source_date   TEXT,                          -- 来源发布日期
    as_of         TEXT NOT NULL,                 -- 数据时间戳（编辑核实日 / 数据层截至时间）
    jd_status     TEXT NOT NULL CHECK (jd_status IN ('linked', 'official_page', 'blocked', 'none')),
    jd_url        TEXT,                          -- 官方 JD 页（official_page / blocked 时的招聘页）
    jd_company    TEXT,                          -- linked：数据层中的公司名
    open_jobs     INTEGER,                       -- linked：数据层在招岗位数
    notes         TEXT
);
CREATE INDEX idx_entry_group ON entry(group_name);
CREATE INDEX idx_entry_type  ON entry(project_type);

-- 覆盖目标（来自 targets/top_companies.yaml），用于 stats 计算日历/JD 覆盖率
CREATE TABLE target (
    name           TEXT PRIMARY KEY,
    sector         TEXT NOT NULL,
    blocked_reason TEXT,                         -- 无法合规抓取 JD 的原因
    data_companies TEXT NOT NULL DEFAULT '[]'    -- JSON：数据层中匹配到的公司名
);

-- 投递/JD/来源链接每日探活
CREATE TABLE link_check (
    url             TEXT PRIMARY KEY,
    status          TEXT NOT NULL CHECK (status IN ('ok', 'dead', 'error')),
    http_status     INTEGER,
    checked_at      TEXT NOT NULL,
    first_failed_at TEXT                         -- 连续失败的起始时间；恢复后清空
);

CREATE TABLE build (
    id      INTEGER PRIMARY KEY,
    ts      TEXT NOT NULL,
    manual  INTEGER NOT NULL,
    auto    INTEGER NOT NULL,
    data_as_of TEXT
);
