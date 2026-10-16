CREATE TABLE workflows (id TEXT PRIMARY KEY, name TEXT NOT NULL, enabled BOOLEAN NOT NULL DEFAULT FALSE, revision INTEGER NOT NULL, graph JSON NOT NULL, runtime JSON NOT NULL, updated DOUBLE PRECISION NOT NULL);
CREATE TABLE workflow_runs (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, trigger_id TEXT NOT NULL, occurrence TEXT NOT NULL, graph JSON NOT NULL, state JSON NOT NULL, status TEXT NOT NULL, created DOUBLE PRECISION NOT NULL, updated DOUBLE PRECISION NOT NULL, UNIQUE(revision, trigger_id, occurrence));
CREATE INDEX ix_workflow_runs_status ON workflow_runs(status);
CREATE INDEX ix_workflow_runs_created ON workflow_runs(created);
