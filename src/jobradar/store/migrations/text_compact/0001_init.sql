-- 只读分发格式：岗位关联和观测时间独立保留，重复正文无损压缩后仅存一份。
PRAGMA application_id=0x4A524354;
CREATE TABLE jd_body (
    id INTEGER PRIMARY KEY,
    digest BLOB NOT NULL UNIQUE,
    payload BLOB NOT NULL
);
CREATE TABLE jd_ref (
    job_id TEXT PRIMARY KEY,
    body_id INTEGER NOT NULL REFERENCES jd_body(id),
    fetched_at TEXT NOT NULL
) WITHOUT ROWID;
CREATE INDEX idx_jd_ref_body ON jd_ref(body_id);
CREATE VIEW job_text AS
SELECT r.job_id,
       json_extract(jobradar_unpack(b.payload), '$[0]') AS description,
       json_extract(jobradar_unpack(b.payload), '$[1]') AS requirements,
       r.fetched_at
FROM jd_ref r JOIN jd_body b ON b.id=r.body_id;
