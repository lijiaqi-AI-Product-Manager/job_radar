-- jd_text.db：岗位描述/要求原文，体积大，用户按需下载。

CREATE TABLE job_text (
    job_id       TEXT PRIMARY KEY,               -- 对应 jobs.db 的 job.id（跨库，无外键）
    description  TEXT,
    requirements TEXT,
    fetched_at   TEXT NOT NULL
);
