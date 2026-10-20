-- jobs.db：轻量主库（岗位、事件、抓取记录）。时间一律为 UTC ISO8601：YYYY-MM-DDTHH:MM:SSZ

CREATE TABLE company (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE job (
    id            TEXT PRIMARY KEY,              -- "<source_id>:<source_job_id>"
    company_id    INTEGER NOT NULL REFERENCES company(id),
    source_id     TEXT NOT NULL,
    source_job_id TEXT NOT NULL,
    url           TEXT NOT NULL,
    title         TEXT NOT NULL,
    category      TEXT,                          -- 归一后的职类，见 taxonomy/
    subcategory   TEXT,
    recruit_type  TEXT NOT NULL CHECK (recruit_type IN ('campus', 'intern', 'social')),
    grad_year     INTEGER,                       -- 届别，如 2027
    batch         TEXT,                          -- 提前批 / 正式批 / 补录 等
    cities        TEXT NOT NULL DEFAULT '[]',    -- JSON 数组
    degree_min    TEXT,
    department    TEXT,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    closed_at     TEXT,                          -- NULL = 仍在招
    miss_count    INTEGER NOT NULL DEFAULT 0,    -- 连续成功抓取中缺席的次数
    content_hash  TEXT NOT NULL,
    UNIQUE (source_id, source_job_id)
);
CREATE INDEX idx_job_company ON job(company_id);
CREATE INDEX idx_job_source  ON job(source_id);
CREATE INDEX idx_job_open    ON job(closed_at);

CREATE TABLE job_event (
    id     INTEGER PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES job(id),
    ts     TEXT NOT NULL,
    type   TEXT NOT NULL CHECK (type IN ('open', 'close', 'change', 'reopen')),
    diff   TEXT                                  -- JSON，change 时记录变化的字段名
);
CREATE INDEX idx_event_ts  ON job_event(ts);
CREATE INDEX idx_event_job ON job_event(job_id);

CREATE TABLE source_run (
    id         INTEGER PRIMARY KEY,
    source_id  TEXT NOT NULL,
    ts         TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('ok', 'failed', 'rejected')),
    job_count  INTEGER NOT NULL DEFAULT 0,
    duration_s REAL,
    error      TEXT
);
CREATE INDEX idx_run_source_ts ON source_run(source_id, ts);
