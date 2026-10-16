ALTER TABLE commands ALTER COLUMN power DROP NOT NULL;
ALTER TABLE commands ADD COLUMN payload JSON;
ALTER TABLE states ADD COLUMN time_known BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE measurements ADD COLUMN time_known BOOLEAN NOT NULL DEFAULT TRUE;
CREATE TABLE automations (
    id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, enabled BOOLEAN NOT NULL,
    definition JSON NOT NULL, runtime JSON NOT NULL, updated DOUBLE PRECISION NOT NULL
);
CREATE TABLE automation_runs (
    id VARCHAR PRIMARY KEY, rule_id VARCHAR NOT NULL, occurrence VARCHAR NOT NULL,
    definition JSON NOT NULL, status VARCHAR NOT NULL, results JSON NOT NULL,
    created DOUBLE PRECISION NOT NULL, UNIQUE (rule_id, occurrence)
);
CREATE INDEX ix_automation_runs_rule_id ON automation_runs(rule_id);
CREATE INDEX ix_automation_runs_created ON automation_runs(created);
