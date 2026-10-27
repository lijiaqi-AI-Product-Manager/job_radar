-- 岗位的网申时间窗（2026-10-26 新增）。
--
-- 背景：大易（hotjob）的列表接口直接返回 endDate / publishDate / workPlaceStr，
-- 但原来的 Job 模型没有这两个字段，抓到就丢了——等于把「什么时候截止」这条最有用的
-- 信息扔在接口里不要。日历侧靠高校简章才补到 26% 的截止日，而接口型源本来就有。
--
-- apply_end：网申截止时间（UTC ISO8601）。NULL = 源没给（不是"长期有效"）。
--    大易对长期开放的岗给 3000-01-01，导入时归一成 NULL，避免污染"快截止"筛选。
-- publish_at：岗位发布时间（UTC ISO8601）。NULL = 源没给。
--    用途：按发布日期推断批次（8-11 月发布多为秋招、3-5 月多为春招）。
--
-- 不改 0001：CLAUDE.md 规定已有迁移永不修改。

ALTER TABLE job ADD COLUMN apply_end  TEXT;
ALTER TABLE job ADD COLUMN publish_at TEXT;

CREATE INDEX idx_job_apply_end ON job(apply_end) WHERE apply_end IS NOT NULL;
