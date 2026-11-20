export type Role = 'operator' | 'viewer';
export type Session = {token: string; username: string; memberships: {workspace: string; role: Role}[]};
export type Run = {
  id: string; parent_id: string | null; status: string; revision: string; mode: string;
  correlation: string; actor: string; start_date: string; end_date: string; created_at: string;
};
export type Detail = {
  run: Run; events: {seq: number; task: string; state: string; message: string; at: string}[];
  retry: {id: string; status: string} | null;
};
export type Failure = {row_num: number; order_id: string; reason: string};
export type Audit = {id: number; run_id: string; workspace: string; actor: string; action: string; at: string};
type Cohort = {n: number; failures: number; percent: number};
export type Comparison = {
  clean: Cohort; changed: Cohort; difference_pp: number; p_value: number | null; ci95_pp: number[] | null;
};

export async function request<T>(path: string, token?: string, body?: object, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    method: body ? 'POST' : 'GET', signal,
    headers: {...(token ? {Authorization: `Bearer ${token}`} : {}),
      ...(body ? {'Content-Type': 'application/json'} : {})},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (response.status === 204) return undefined as T;
  const payload = await response.json();
  if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : `Request failed (${response.status})`);
  return payload;
}

export async function events(path: string, token: string, signal: AbortSignal,
  update: () => void, state: (status: string) => void) {
  let last = '';
  while (!signal.aborted) {
    try {
      const response = await fetch(path, {signal, headers: {
        Authorization: `Bearer ${token}`, ...(last ? {'Last-Event-ID': last} : {}),
      }});
      if (response.status === 401 || response.status === 403) {
        state('Sign-in required for live updates');
        return;
      }
      if (!response.ok || !response.body) throw new Error('Event connection failed');
      const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = '';
      try {
        while (true) {
          const chunk = await reader.read();
          if (chunk.done) break;
          buffer += chunk.value;
          let boundary = buffer.indexOf('\n\n');
          while (boundary >= 0) {
            const event = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            const id = event.match(/^id: (\d+)$/m)?.[1];
            if (id) last = id;
            if (event.includes('event: ready')) state('Live');
            if (event.includes('event: ready') || event.includes('event: run')) update();
            boundary = buffer.indexOf('\n\n');
          }
        }
      } finally {
        reader.releaseLock();
      }
    } catch {
      if (signal.aborted) return;
    }
    if (!signal.aborted) {
      state('Reconnecting');
      await new Promise(resolve => setTimeout(resolve, 1500));
    }
  }
}
