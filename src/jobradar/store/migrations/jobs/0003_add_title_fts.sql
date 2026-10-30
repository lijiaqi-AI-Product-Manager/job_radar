-- 外部内容索引不复制职位标题；trigram 支持原有子串语义，detail=none 降低分发体积。
CREATE VIRTUAL TABLE job_fts USING fts5(
    title, content='job', content_rowid='rowid', tokenize='trigram', detail=none, columnsize=0
);

CREATE TRIGGER job_fts_insert AFTER INSERT ON job BEGIN
    INSERT INTO job_fts(rowid, title) VALUES (new.rowid, new.title);
END;

CREATE TRIGGER job_fts_delete AFTER DELETE ON job BEGIN
    INSERT INTO job_fts(job_fts, rowid, title) VALUES ('delete', old.rowid, old.title);
END;

CREATE TRIGGER job_fts_update AFTER UPDATE OF title ON job
WHEN old.title IS NOT new.title BEGIN
    INSERT INTO job_fts(job_fts, rowid, title) VALUES ('delete', old.rowid, old.title);
    INSERT INTO job_fts(rowid, title) VALUES (new.rowid, new.title);
END;

INSERT INTO job_fts(job_fts) VALUES ('rebuild');
