import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {events, request} from './client';
import type {Audit, Comparison, Detail, Failure, Run, Session} from './client';
import './styles.css';

const dateTime = (value: string) => new Date(value).toLocaleString();
const shortId = (id: string) => id.slice(0, 8);
const message = (error: unknown) => error instanceof Error ? error.message : 'Request failed';

function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function login(form: React.FormEvent<HTMLFormElement>) {
    form.preventDefault();
    const data = Object.fromEntries(new FormData(form.currentTarget));
    setBusy(true);
    setError('');
    try {
      setSession(await request<Session>('/api/sign-in', undefined, data));
    } catch (error) { setError(message(error)); }
    finally { setBusy(false); }
  }
  if (session) return <Console session={session} signOut={() => {
    void request('/api/sign-out', session.token, {}).catch(() => undefined);
    setSession(null);
  }}/>;
  return <main className="login"><section className="card">
    <div className="brand"><span className="mark" aria-hidden>∿</span> PipelineOps</div>
    <h1>Sign in</h1>
    <p>Monitor and recover the synthetic orders pipeline.</p>
    <form onSubmit={login}>
      <label>Username<input name="username" autoComplete="username" required /></label>
      <label>Password<input name="password" autoComplete="current-password" type="password" required /></label>
      {error && <p role="alert" className="error">{error}</p>}
      <button disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
    </form>
  </section></main>;
}

function Status({value}: {value: string}) {
  return <span className={`status ${value}`}>{value}</span>;
}

function Console({session, signOut}: {session: Session; signOut: () => void}) {
  const [workspace, setWorkspace] = useState(session.memberships[0]?.workspace || '');
  const role = session.memberships.find(item => item.workspace === workspace)?.role;
  const base = `/api/workspaces/${workspace}`;
  const token = session.token;
  const [page, setPage] = useState<'runs' | 'audit'>('runs');
  const [selected, setSelected] = useState('');
  const [state, setState] = useState('Connecting');
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [failures, setFailures] = useState<Failure[]>([]);
  const [audit, setAudit] = useState<Audit[] | null>(null);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [filter, setFilter] = useState({status: '', start: '', end: ''});
  const [mode, setMode] = useState('backfill');
  const [revision, setRevision] = useState('clean');
  const [start, setStart] = useState('2025-01-01');
  const [end, setEnd] = useState('2025-01-04');
  const [corrected, setCorrected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [actionError, setActionError] = useState('');
  const [version, setVersion] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setState('Connecting');
    void events(base + '/events', token, controller.signal, () => setVersion(n => n + 1), setState);
    return () => controller.abort();
  }, [base, token]);

  useEffect(() => {
    const controller = new AbortController();
    request<Comparison>(base + '/comparison', token, undefined, controller.signal).then(setComparison)
      .catch(error => { if (!controller.signal.aborted) setLoadError(message(error)); });
    return () => controller.abort();
  }, [base, token]);

  useEffect(() => {
    const controller = new AbortController();
    const signal = controller.signal;
    async function load() {
      try {
        if (page === 'audit') {
          setAudit(await request<Audit[]>(base + '/audit', token, undefined, signal));
        } else if (selected) {
          const path = base + '/runs/' + selected;
          const [item, issues] = await Promise.all([
            request<Detail>(path, token, undefined, signal),
            request<Failure[]>(path + '/failures', token, undefined, signal),
          ]);
          setDetail(item);
          setFailures(issues);
        } else {
          const params = new URLSearchParams(Object.entries(filter).filter(([, value]) => value));
          setRuns(await request<Run[]>(base + '/runs?' + params, token, undefined, signal));
        }
        if (!signal.aborted) setLoadError('');
      } catch (error) {
        if (!signal.aborted) setLoadError(message(error));
      }
    }
    void load();
    return () => controller.abort();
  }, [base, token, page, selected, filter, version]);

  function open(id: string) {
    setPage('runs');
    setSelected(id);
    setDetail(null);
    setFailures([]);
    setCorrected(false);
    setActionError('');
    setLoadError('');
  }
  async function submit(path: string, body: object) {
    setBusy(true);
    setActionError('');
    try {
      const run = await request<Run>(base + path, token, body);
      open(run.id);
      setVersion(n => n + 1);
    } catch (error) { setActionError(message(error)); }
    finally { setBusy(false); }
  }

  return <>
    <header><div className="brand"><span className="mark" aria-hidden>∿</span> PipelineOps</div>
      <nav aria-label="Console">
        <button className={page === 'runs' ? 'active ghost' : 'ghost'} onClick={() => open('')}>Runs</button>
        <button className={page === 'audit' ? 'active ghost' : 'ghost'} onClick={() => {
          setActionError(''); setLoadError(''); setPage('audit');
        }}>Audit</button>
      </nav>
      <div className="identity">
        <label className="workspace">Workspace<select value={workspace} disabled={busy} onChange={event => {
          setWorkspace(event.target.value); setRuns(null); setAudit(null); setComparison(null); open('');
        }}>{session.memberships.map(item => <option key={item.workspace}>{item.workspace}</option>)}</select></label>
        <span>{session.username} · {role}</span><button className="ghost" onClick={signOut}>Sign out</button>
      </div>
    </header>
    <main>
      <div className="heading"><h1>{page === 'audit' ? 'Audit history' : selected ? 'Run detail' : 'Pipeline runs'}</h1>
        <span className="live" role="status">{state}</span></div>
      {(loadError || actionError) && <p className="error" role="alert">{actionError || loadError}</p>}
      {page === 'audit' ? <section className="card">
        {audit === null ? <p>Loading audit history…</p> : !audit.length ? <p>No audit events yet.</p> :
          <div className="table"><table><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Workspace</th><th>Run</th></tr></thead>
            <tbody>{audit.map(row => <tr key={row.id}><td>{dateTime(row.at)}</td><td>{row.actor}</td>
              <td>{row.action}</td><td>{row.workspace}</td><td><button className="link" onClick={() => open(row.run_id)}>{shortId(row.run_id)}</button></td></tr>)}</tbody>
          </table></div>}
      </section> : selected ? <section className="card">
        <button className="link" onClick={() => open('')}>← All runs</button>
        {!detail ? <p>Loading run…</p> : <>
          <div className="heading"><h2>Run {shortId(detail.run.id)}</h2><Status value={detail.run.status}/></div>
          <dl><div><dt>Source revision</dt><dd>{detail.run.revision}</dd></div>
            <div><dt>Source window (end excluded)</dt><dd>{detail.run.start_date} → {detail.run.end_date}</dd></div>
            <div><dt>Correlation ID</dt><dd><code>{detail.run.correlation}</code></dd></div>
            {detail.run.parent_id && <div><dt>Original run</dt><dd><button className="link" onClick={() => open(detail.run.parent_id!)}>{shortId(detail.run.parent_id)}</button></dd></div>}
            {detail.retry && <div><dt>Linked retry</dt><dd><button className="link" onClick={() => open(detail.retry!.id)}>{shortId(detail.retry.id)}</button> · {detail.retry.status}</dd></div>}
          </dl>
          {role === 'operator' && detail.run.status === 'failed' && !detail.retry &&
            <div className="actions">{detail.run.revision === 'changed' &&
              <label className="check"><input type="checkbox" checked={corrected} onChange={event => setCorrected(event.target.checked)} />Use corrected demo fixture</label>}
              <button disabled={busy} onClick={() => void submit('/runs/' + selected + '/retry', {use_corrected_fixture: corrected})}>Retry run</button>
            </div>}
          <h3>Task progress</h3>
          <ol className="timeline">{detail.events.map(event => <li key={event.seq}>
            <time>{dateTime(event.at)}</time><strong>{event.task}</strong><Status value={event.state}/><span>{event.message}</span>
          </li>)}</ol>
          <h3>Validation failures</h3>
          {!failures.length ? <p>No validation failures recorded.</p> :
            <div className="table"><table><thead><tr><th>Row</th><th>Order ID</th><th>Reason</th></tr></thead>
              <tbody>{failures.map(item => <tr key={item.row_num + item.reason}><td>{item.row_num}</td><td>{item.order_id}</td><td>{item.reason}</td></tr>)}</tbody></table></div>}
        </>}
      </section> : <>
        {role === 'operator' && <section className="card"><h2>Start a run</h2>
          <form className="controls" onSubmit={event => {
            event.preventDefault(); void submit('/runs', {mode, revision, ...(mode === 'backfill' ? {start, end} : {})});
          }}>
            <label>Source revision<select value={revision} onChange={e => setRevision(e.target.value)}>
              <option value="clean">Clean</option><option value="changed">Changed (invalid)</option>
              <option value="corrected">Corrected</option><option value="transient">Temporary 503, then clean</option>
            </select></label>
            <label>Mode<select value={mode} onChange={e => setMode(e.target.value)}><option value="backfill">Backfill</option>
              <option value="incremental">Incremental</option></select></label>
            {mode === 'backfill' && <><label>Source start<input type="date" required value={start} onChange={e => setStart(e.target.value)}/></label>
              <label>Source end (exclusive)<input type="date" required value={end} onChange={e => setEnd(e.target.value)}/></label></>}
            <button disabled={busy}>Start run</button>
          </form></section>}
        <section className="card"><h2>Run history</h2>
          <div className="controls"><label>Status<select value={filter.status} onChange={e => setFilter({...filter, status: e.target.value})}>
            {['', 'queued', 'running', 'succeeded', 'failed'].map(value => <option key={value} value={value}>{value || 'All statuses'}</option>)}
          </select></label>
            <label>Created from<input type="date" value={filter.start} onChange={e => setFilter({...filter, start: e.target.value})}/></label>
            <label>Created through<input type="date" value={filter.end} onChange={e => setFilter({...filter, end: e.target.value})}/></label>
          </div>
          {runs === null ? <p>Loading runs…</p> : !runs.length ? <p>No matching runs.</p> :
            <div className="table"><table><thead><tr><th>Run</th><th>Revision</th><th>Status</th><th>Created</th><th>Mode</th></tr></thead>
              <tbody>{runs.map(run => <tr key={run.id}><td><button className="link" onClick={() => open(run.id)}>{shortId(run.id)}</button></td>
                <td>{run.revision}</td><td><Status value={run.status}/></td><td>{dateTime(run.created_at)}</td><td>{run.mode}</td></tr>)}</tbody>
            </table></div>}
        </section>
        <section className="card"><h2>Synthetic input quality</h2>{comparison ? <>
          <div className="stats">
            {([['Baseline', comparison.clean], ['Changed', comparison.changed]] as const).map(([name, cohort]) =>
              <div key={name}><strong>{cohort.percent.toFixed(1)}%</strong><span>{name} · {cohort.failures} / {cohort.n} rejected</span></div>)}
            <div><strong>{comparison.difference_pp.toFixed(1)} pp</strong><span>Changed minus baseline</span></div>
          </div>
          <p>{comparison.ci95_pp && comparison.p_value !== null ?
            <>95% CI {comparison.ci95_pp.map(x => x.toFixed(2)).join(' to ')} pp · p = {comparison.p_value.toPrecision(3)}</> :
            'Too few successes or failures for the normal approximation.'}</p>
          <p className="subtle">Independent synthetic cohorts. A two-sided two-proportion z-test uses a pooled standard error.
            The 95% Wald interval uses an unpooled standard error. Each order counts once.</p>
        </> : <p>Loading input comparison…</p>}</section>
      </>}
    </main>
  </>;
}

createRoot(document.getElementById('root')!).render(<App />);
