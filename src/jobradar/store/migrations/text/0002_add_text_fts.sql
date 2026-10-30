-- JD 外部内容索引；不改写原文，保持旧库可一次性回填，后续靠触发器增量维护。
CREATE VIRTUAL TABLE job_text_fts USING fts5(
    description, requirements, content='job_text', content_rowid='rowid',
    tokenize='trigram', detail=none, columnsize=0
);

CREATE TRIGGER job_text_fts_insert AFTER INSERT ON job_text BEGIN
    INSERT INTO job_text_fts(rowid, description, requirements)
    VALUES (new.rowid, new.description, new.requirements);
END;

CREATE TRIGGER job_text_fts_delete AFTER DELETE ON job_text BEGIN
    INSERT INTO job_text_fts(job_text_fts, rowid, description, requirements)
    VALUES ('delete', old.rowid, old.description, old.requirements);
END;

CREATE TRIGGER job_text_fts_update AFTER UPDATE OF description, requirements ON job_text
WHEN old.description IS NOT new.description OR old.requirements IS NOT new.requirements BEGIN
    INSERT INTO job_text_fts(job_text_fts, rowid, description, requirements)
    VALUES ('delete', old.rowid, old.description, old.requirements);
    INSERT INTO job_text_fts(rowid, description, requirements)
    VALUES (new.rowid, new.description, new.requirements);
END;

INSERT INTO job_text_fts(job_text_fts) VALUES ('rebuild');
