import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react';
import { useMatch, useNavigate } from 'react-router-dom';
import { api, ApiError } from '../api/http';
import { streamEvents } from '../api/sse';

const ChatContext = createContext(null);

const CONVERSATION_PAGE = 30;
const MESSAGE_PAGE = 100;
const MAX_RECONNECTS = 5;

const sleep = (ms, signal) =>
  new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => {
      clearTimeout(timer);
      resolve();
    });
  });

const byRecent = (a, b) => new Date(b.last_message_at) - new Date(a.last_message_at);

function errorText(err) {
  return err instanceof ApiError ? err.detail : err?.message || 'Something went wrong.';
}

export function ChatProvider({ children }) {
  const navigate = useNavigate();
  const match = useMatch('/c/:id');
  const activeId = match?.params.id ?? null;

  // Conversation list (sidebar)
  const [conversations, setConversations] = useState([]);
  const [listState, setListState] = useState({ loading: true, error: null, hasMore: false, loadingMore: false });
  // Active conversation
  const [detail, setDetail] = useState(null);
  const [messages, setMessages] = useState([]);
  const [msgState, setMsgState] = useState({ loading: false, error: null, hasMore: false, loadingMore: false });
  // Generation in progress for the active conversation: { id, conversationId, statusText, stopping }
  const [generation, setGeneration] = useState(null);
  const [notice, setNotice] = useState(null);
  const [aiConfigured, setAiConfigured] = useState(true);

  const streamRef = useRef(null); // { controller, generationId }
  const sendInFlightRef = useRef(false);
  const suppressLoadRef = useRef(null); // conversation id whose state was just built locally
  const reloadTick = useRef(0);
  const [reloadKey, setReloadKey] = useState(0);

  // ---- helpers --------------------------------------------------------------------------

  const abortStream = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.controller.abort(); // detaches only; the server keeps generating
      streamRef.current = null;
    }
  }, []);

  const upsertConversation = useCallback((conv) => {
    setConversations((list) => {
      const exists = list.some((c) => c.id === conv.id);
      const next = exists ? list.map((c) => (c.id === conv.id ? { ...c, ...conv } : c)) : [conv, ...list];
      return next.sort(byRecent);
    });
    setDetail((d) => (d && d.id === conv.id ? { ...d, ...conv } : d));
  }, []);

  // ---- streaming ------------------------------------------------------------------------

  const consume = useCallback(
    async (generationId, assistantId, conversationId) => {
      abortStream();
      const controller = new AbortController();
      streamRef.current = { controller, generationId };
      setGeneration({ id: generationId, conversationId, statusText: 'Starting…', stopping: false });

      let lastId = 0;
      let finished = false;
      const patch = (fn) => setMessages((ms) => ms.map((m) => (m.id === assistantId ? fn(m) : m)));

      const onEvent = (ev) => {
        if (ev.id) lastId = ev.id;
        const d = ev.data;
        switch (ev.event) {
          case 'status':
            setGeneration((g) => (g && g.id === generationId ? { ...g, statusText: d.message } : g));
            break;
          case 'message_delta':
            patch((m) => ({ ...m, content: m.content + d.text }));
            break;
          case 'message_completed':
            patch((m) => ({
              ...m,
              status: 'completed',
              input_tokens: d.input_tokens,
              output_tokens: d.output_tokens,
              error_message: null,
            }));
            finished = true;
            break;
          case 'generation_failed':
            patch((m) => ({ ...m, status: d.interrupted ? 'interrupted' : 'failed', error_message: d.error }));
            finished = true;
            break;
          case 'generation_cancelled':
            patch((m) => ({ ...m, status: 'cancelled' }));
            finished = true;
            break;
          default:
            break;
        }
      };

      let attempts = 0;
      while (!finished && !controller.signal.aborted) {
        try {
          // Reconnects resume after the last event we saw (Last-Event-ID), so nothing repeats.
          await streamEvents(`/generations/${generationId}/events`, {
            signal: controller.signal,
            lastEventId: lastId || undefined,
            onEvent,
          });
        } catch (err) {
          if (controller.signal.aborted) return;
          if (err instanceof ApiError && [401, 403, 404].includes(err.status)) break;
        }
        if (finished || controller.signal.aborted) break;
        attempts += 1;
        if (attempts > MAX_RECONNECTS) break;
        await sleep(Math.min(500 * attempts, 3000), controller.signal);
      }

      if (controller.signal.aborted) return;
      if (streamRef.current?.controller === controller) streamRef.current = null;
      setGeneration((g) => (g && g.id === generationId ? null : g));

      if (!finished) {
        setNotice('Lost the connection to the server. Showing the latest saved state.');
        reloadTick.current += 1;
        setReloadKey(reloadTick.current); // re-sync from the database
      }
      try {
        upsertConversation(await api.get(`/conversations/${conversationId}`));
      } catch {
        /* sidebar refresh is best-effort */
      }
    },
    [abortStream, upsertConversation],
  );

  // ---- loading data ---------------------------------------------------------------------

  useEffect(() => {
    let active = true;
    fetch('/api/v1/health')
      .then((r) => (r.ok ? r.json() : null))
      .then((h) => active && h && setAiConfigured(h.ai_configured !== false))
      .catch(() => {});
    api
      .get(`/conversations?limit=${CONVERSATION_PAGE}`)
      .then((page) => {
        if (!active) return;
        setConversations(page.items);
        setListState({ loading: false, error: null, hasMore: page.has_more, loadingMore: false });
      })
      .catch((err) => active && setListState({ loading: false, error: errorText(err), hasMore: false, loadingMore: false }));
    return () => {
      active = false;
    };
  }, []);

  // Load the active conversation whenever the route (or a forced re-sync) changes.
  useEffect(() => {
    if (activeId && suppressLoadRef.current === activeId) {
      suppressLoadRef.current = null; // state was just built locally; preserve it and its stream
      return undefined;
    }
    abortStream();
    setGeneration(null);
    if (!activeId) {
      setDetail(null);
      setMessages([]);
      setMsgState({ loading: false, error: null, hasMore: false, loadingMore: false });
      return undefined;
    }
    let cancelled = false;
    setMsgState({ loading: true, error: null, hasMore: false, loadingMore: false });
    setMessages([]);
    (async () => {
      try {
        const [conv, page] = await Promise.all([
          api.get(`/conversations/${activeId}`),
          api.get(`/conversations/${activeId}/messages?limit=${MESSAGE_PAGE}`),
        ]);
        if (cancelled) return;
        setDetail(conv);
        setMessages(page.items);
        setMsgState({ loading: false, error: null, hasMore: page.has_more, loadingMore: false });

        // Re-attach to a generation that is still running (page reload, or switching back).
        const last = page.items[page.items.length - 1];
        if (conv.active_generation_id && last?.role === 'assistant') {
          setMessages((ms) => ms.map((m) => (m.id === last.id ? { ...m, content: '', status: 'streaming' } : m)));
          consume(conv.active_generation_id, last.id, activeId);
        }
      } catch (err) {
        if (cancelled) return;
        setMsgState({
          loading: false,
          error: err instanceof ApiError && err.status === 404 ? 'This conversation could not be found.' : errorText(err),
          hasMore: false,
          loadingMore: false,
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeId, reloadKey, abortStream, consume]);

  // Stop streaming when the provider unmounts (for example on logout).
  useEffect(() => abortStream, [abortStream]);

  // ---- actions --------------------------------------------------------------------------

  const loadMoreConversations = async () => {
    setListState((s) => ({ ...s, loadingMore: true }));
    try {
      const page = await api.get(`/conversations?limit=${CONVERSATION_PAGE}&offset=${conversations.length}`);
      setConversations((list) => {
        const known = new Set(list.map((c) => c.id));
        return [...list, ...page.items.filter((c) => !known.has(c.id))];
      });
      setListState((s) => ({ ...s, hasMore: page.has_more, loadingMore: false }));
    } catch (err) {
      setListState((s) => ({ ...s, loadingMore: false }));
      setNotice(errorText(err));
    }
  };

  const loadEarlierMessages = async () => {
    if (!activeId || messages.length === 0) return;
    setMsgState((s) => ({ ...s, loadingMore: true }));
    try {
      const page = await api.get(
        `/conversations/${activeId}/messages?limit=${MESSAGE_PAGE}&before_sequence=${messages[0].sequence_number}`,
      );
      setMessages((ms) => [...page.items, ...ms]);
      setMsgState((s) => ({ ...s, hasMore: page.has_more, loadingMore: false }));
    } catch (err) {
      setMsgState((s) => ({ ...s, loadingMore: false }));
      setNotice(errorText(err));
    }
  };

  /** Send immediately into local state, then replace it with the persisted response. */
  const send = async (content) => {
    if (generation || sendInFlightRef.current) return false;
    sendInFlightRef.current = true;
    setNotice(null);
    const conversationId = activeId;
    const pendingId = `pending-${crypto.randomUUID()}`;
    const pendingUserMessage = {
      id: pendingId,
      conversation_id: conversationId,
      sequence_number: (messages[messages.length - 1]?.sequence_number ?? 0) + 1,
      role: 'user',
      content,
      status: 'completed',
      model_name: null,
      input_tokens: null,
      output_tokens: null,
      created_at: new Date().toISOString(),
      error_message: null,
    };
    setMessages((ms) => [...ms, pendingUserMessage]);
    try {
      const res = conversationId
        ? await api.post(`/conversations/${conversationId}/messages`, { content })
        : await api.post('/conversations/start', { content });
      setMessages((ms) => [
        ...ms.filter((m) => m.id !== pendingId),
        res.user_message,
        res.assistant_message,
      ]);
      upsertConversation(res.conversation);
      setDetail(res.conversation);
      if (!conversationId) {
        suppressLoadRef.current = res.conversation.id;
        navigate(`/c/${res.conversation.id}`);
      }
      consume(res.generation_id, res.assistant_message.id, res.conversation.id);
      return true;
    } catch (err) {
      setMessages((ms) => ms.filter((m) => m.id !== pendingId));
      setNotice(errorText(err));
      return false;
    } finally {
      sendInFlightRef.current = false;
    }
  };

  const stop = async () => {
    if (!generation || generation.stopping) return;
    setGeneration({ ...generation, stopping: true, statusText: 'Stopping…' });
    try {
      await api.post(`/generations/${generation.id}/cancel`);
      // The event stream delivers "generation_cancelled" and finishes the UI update.
    } catch (err) {
      setNotice(errorText(err));
      setGeneration((g) => (g ? { ...g, stopping: false } : g));
    }
  };

  const regenerate = async () => {
    if (generation || !activeId) return;
    setNotice(null);
    try {
      const res = await api.post(`/conversations/${activeId}/regenerate`);
      const fresh = { ...res.assistant_message, content: '', error_message: null };
      setMessages((ms) => ms.map((m) => (m.id === fresh.id ? fresh : m)));
      upsertConversation(res.conversation);
      consume(res.generation_id, fresh.id, activeId);
    } catch (err) {
      setNotice(errorText(err));
    }
  };

  const renameConversation = async (id, title) => {
    try {
      upsertConversation(await api.patch(`/conversations/${id}`, { title }));
      return true;
    } catch (err) {
      setNotice(errorText(err));
      return false;
    }
  };

  const deleteConversation = async (id) => {
    try {
      await api.del(`/conversations/${id}`);
      setConversations((list) => list.filter((c) => c.id !== id));
      if (id === activeId) navigate('/');
      return true;
    } catch (err) {
      setNotice(errorText(err));
      return false;
    }
  };

  const retryLoad = () => {
    reloadTick.current += 1;
    setReloadKey(reloadTick.current);
  };

  const value = {
    activeId,
    activeConversation: detail && detail.id === activeId ? detail : null,
    conversations,
    listState,
    messages,
    msgState,
    generation,
    notice,
    aiConfigured,
    dismissNotice: () => setNotice(null),
    loadMoreConversations,
    loadEarlierMessages,
    send,
    stop,
    regenerate,
    renameConversation,
    deleteConversation,
    retryLoad,
  };
  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

export function useChat() {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error('useChat must be used inside ChatProvider');
  return ctx;
}
