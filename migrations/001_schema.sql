CREATE TABLE workspaces (id text PRIMARY KEY, name text NOT NULL);
CREATE TABLE users (username text PRIMARY KEY, password_hash text NOT NULL);
CREATE TABLE memberships (
  workspace text REFERENCES workspaces, username text REFERENCES users,
  role text NOT NULL CHECK (role IN ('viewer','operator')), PRIMARY KEY(workspace,username)
);
CREATE TABLE sessions (
  token_hash text PRIMARY KEY, username text NOT NULL REFERENCES users,
  expires_at timestamptz NOT NULL DEFAULT now()+interval '8 hours'
);
CREATE TABLE runs (
  id uuid PRIMARY KEY, workspace text NOT NULL REFERENCES workspaces,
  correlation uuid NOT NULL UNIQUE, parent_id uuid UNIQUE,
  actor text NOT NULL, mode text NOT NULL CHECK (mode IN ('incremental','backfill')),
  revision text NOT NULL CHECK (revision IN ('clean','changed','corrected','transient')),
  start_date date NOT NULL, end_date date NOT NULL CHECK (end_date > start_date),
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','failed','succeeded')),
  created_at timestamptz NOT NULL DEFAULT now(), started_at timestamptz, ended_at timestamptz,
  dispatched_at timestamptz,
  UNIQUE(workspace,id), FOREIGN KEY(workspace,parent_id) REFERENCES runs(workspace,id)
);
CREATE TABLE run_events (
  seq bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  workspace text NOT NULL, run_id uuid NOT NULL, correlation uuid NOT NULL,
  task text NOT NULL, state text NOT NULL, message text NOT NULL,
  at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(workspace,run_id) REFERENCES runs(workspace,id)
);
CREATE INDEX run_events_workspace_seq ON run_events(workspace,seq);
CREATE INDEX run_events_run_seq ON run_events(run_id,seq);
CREATE TABLE staged (
  run_id uuid REFERENCES runs, row_num int, payload jsonb NOT NULL, PRIMARY KEY(run_id,row_num)
);
CREATE TABLE validation_failures (
  run_id uuid REFERENCES runs, row_num int, order_id text, reason text NOT NULL,
  PRIMARY KEY(run_id,row_num,reason)
);
CREATE TABLE audit_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, workspace text NOT NULL,
  run_id uuid NOT NULL, actor text NOT NULL, action text NOT NULL,
  at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(workspace,run_id) REFERENCES runs(workspace,id)
);
CREATE INDEX audit_workspace_id ON audit_events(workspace,id DESC);
CREATE TABLE orders (
  workspace text NOT NULL, order_id text NOT NULL, order_date date NOT NULL,
  amount numeric(12,2) NOT NULL CHECK(amount > 0), source_run uuid NOT NULL,
  PRIMARY KEY(workspace,order_id),
  FOREIGN KEY(workspace,source_run) REFERENCES runs(workspace,id)
);
CREATE TABLE checkpoints (
  workspace text PRIMARY KEY REFERENCES workspaces,
  last_end date NOT NULL
);
