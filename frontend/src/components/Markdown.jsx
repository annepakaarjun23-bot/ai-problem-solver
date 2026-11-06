import { memo, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useCopy } from '../hooks/useCopy';
import { CheckIcon, CopyIcon } from './Icons';

function textOf(node) {
  if (node == null) return '';
  if (typeof node === 'string') return node;
  if (Array.isArray(node)) return node.map(textOf).join('');
  return textOf(node.props?.children);
}

function CodeBlock({ children }) {
  const { copied, copy } = useCopy();
  // react-markdown renders fenced code as <pre><code class="language-x">…</code></pre>.
  const codeEl = Array.isArray(children) ? children[0] : children;
  const className = codeEl?.props?.className || '';
  const language = /language-([\w+#-]+)/.exec(className)?.[1] || 'text';
  const code = textOf(codeEl).replace(/\n$/, '');

  return (
    <div className="not-prose my-4 overflow-hidden rounded-lg border border-zinc-800 bg-zinc-900">
      <div className="flex items-center justify-between bg-zinc-800 px-3 py-1.5 text-xs text-zinc-300">
        <span className="font-mono">{language}</span>
        <button
          type="button"
          onClick={() => copy(code)}
          className="inline-flex items-center gap-1.5 rounded px-1.5 py-0.5 text-zinc-300 hover:bg-zinc-700 hover:text-white"
          aria-label="Copy code"
        >
          {copied ? <CheckIcon className="h-3.5 w-3.5" /> : <CopyIcon className="h-3.5 w-3.5" />}
          {copied ? 'Copied' : 'Copy code'}
        </button>
      </div>
      <pre className="overflow-x-auto p-4 text-[13px] leading-6 text-zinc-100">
        <code className="font-mono">{code}</code>
      </pre>
    </div>
  );
}

const components = {
  pre: CodeBlock,
  // Links from model output open in a new tab and never leak the opener.
  a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer nofollow" />,
  table: ({ node: _node, ...props }) => (
    <div className="my-4 overflow-x-auto">
      <table {...props} />
    </div>
  ),
};

/** Renders Markdown safely: no raw HTML is interpreted, and unsafe URLs are stripped. */
function Markdown({ content }) {
  const plugins = useMemo(() => [remarkGfm], []);
  return (
    <div className="md">
      <ReactMarkdown remarkPlugins={plugins} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}

export default memo(Markdown);
