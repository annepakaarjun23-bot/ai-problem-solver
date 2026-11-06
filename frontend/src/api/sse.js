// Server-Sent Events over fetch (EventSource cannot send an Authorization header).
import { ApiError, rawFetch } from './http';

/**
 * Open an SSE stream and call onEvent({ id, event, data }) for each event.
 * Resolves when the server closes the stream. Rejects on HTTP errors / network failures.
 * `path` is relative to /api/v1 (for example "/generations/<id>/events").
 */
export async function streamEvents(path, { signal, lastEventId, onEvent }) {
  const headers = { Accept: 'text/event-stream' };
  if (lastEventId) headers['Last-Event-ID'] = String(lastEventId);

  const res = await rawFetch(path, { headers, signal });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === 'string') detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  if (!res.body) throw new Error('Streaming is not supported by this browser.');

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const dispatch = (block) => {
    let id = null;
    let event = 'message';
    const dataLines = [];
    for (const line of block.split('\n')) {
      if (!line || line.startsWith(':')) continue; // comment / heartbeat
      const idx = line.indexOf(':');
      const field = idx === -1 ? line : line.slice(0, idx);
      const value = idx === -1 ? '' : line.slice(idx + 1).replace(/^ /, '');
      if (field === 'id') id = Number(value);
      else if (field === 'event') event = value;
      else if (field === 'data') dataLines.push(value);
    }
    if (dataLines.length === 0) return;
    let data = null;
    try {
      data = JSON.parse(dataLines.join('\n'));
    } catch {
      return;
    }
    onEvent({ id, event, data });
  };

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
      let boundary = buffer.indexOf('\n\n');
      while (boundary !== -1) {
        dispatch(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf('\n\n');
      }
    }
  } finally {
    reader.cancel().catch(() => {});
  }
}
