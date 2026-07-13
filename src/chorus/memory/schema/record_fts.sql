-- record_fts: FTS5 index over intent+body — the BM25 half of retrieval (spec 07 §6). Rebuildable;
-- never the source of truth. Declarative; applied via migrations/.
CREATE VIRTUAL TABLE record_fts USING fts5(run_id UNINDEXED, intent, body);
