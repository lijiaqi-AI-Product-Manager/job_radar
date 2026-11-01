-- 兼容导出保留独立证据表；旧客户端可忽略它，新客户端迁移时可重复创建。
CREATE TABLE IF NOT EXISTS entry_field_evidence (
    entry_id TEXT PRIMARY KEY REFERENCES entry(id) ON DELETE CASCADE,
    fields TEXT NOT NULL
);
