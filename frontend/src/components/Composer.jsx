import { useEffect, useRef, useState } from 'react';
import { SendIcon, StopIcon } from './Icons';

const MAX_LENGTH = 32000;

export default function Composer({ onSend, onStop, generating, stopping, resetKey }) {
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const area = useRef(null);

  // Focus the box when switching conversations.
  useEffect(() => {
    area.current?.focus();
  }, [resetKey]);

  // Grow with content up to a limit.
  useEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [text]);

  const canSend = text.trim().length > 0 && !generating && !sending;

  const submit = async () => {
    if (!canSend) return;
    const submitted = text;
    setSending(true);
    setText('');
    try {
      const ok = await onSend(submitted);
      if (!ok) {
        setText((current) => (current ? `${submitted}\n${current}` : submitted).slice(0, MAX_LENGTH));
      }
    } finally {
      setSending(false);
      area.current?.focus();
    }
  };

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="border-t border-zinc-200 bg-white px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 sm:px-6">
      <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-2xl border border-zinc-300 bg-white p-2 shadow-sm focus-within:border-accent-500 focus-within:ring-2 focus-within:ring-accent-500/20">
        <label htmlFor="composer" className="sr-only">
          Message
        </label>
        <textarea
          id="composer"
          ref={area}
          value={text}
          onChange={(e) => setText(e.target.value.slice(0, MAX_LENGTH))}
          onKeyDown={onKeyDown}
          rows={1}
          placeholder="Describe your problem…"
          className="max-h-56 min-h-[2.5rem] flex-1 resize-none bg-transparent px-2 py-2 text-[15px] leading-6 text-zinc-900 placeholder:text-zinc-400 focus:outline-none focus-visible:ring-0"
        />
        {generating ? (
          <button
            type="button"
            onClick={onStop}
            disabled={stopping}
            className="btn bg-zinc-900 text-white hover:bg-zinc-700"
            aria-label="Stop generating"
          >
            <StopIcon className="h-4 w-4" />
            <span className="hidden sm:inline">{stopping ? 'Stopping…' : 'Stop'}</span>
          </button>
        ) : (
          <button type="button" onClick={submit} disabled={!canSend} className="btn-primary" aria-label="Send message">
            <SendIcon className="h-4 w-4" />
            <span className="hidden sm:inline">Send</span>
          </button>
        )}
      </div>
      <p className="mx-auto mt-2 max-w-3xl text-center text-xs text-zinc-400">
        Enter to send, Shift+Enter for a new line. AI can make mistakes - verify important details.
      </p>
    </div>
  );
}
