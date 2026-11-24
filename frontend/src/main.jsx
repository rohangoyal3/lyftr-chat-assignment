import { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  AlertCircle, BookOpen, Clock3, Database, ListChecks, MessageCircle,
  PencilLine, Plus, SlidersHorizontal, X, Zap,
} from 'lucide-react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import '@fontsource-variable/dm-sans';
import '@fontsource-variable/newsreader';
import { checkHealth, sendChat } from './api';
import './styles.css';

const assistantName = 'Milo';

const suggestions = [
  { Icon: PencilLine, title: 'Help me rewrite an email', prompt: 'Help me rewrite an email so it’s clear and friendly. Ask me to paste my draft first.' },
  { Icon: ListChecks, title: 'Plan a focused work session', prompt: 'Help me plan a focused 45-minute work session. Ask me what I need to finish.' },
  { Icon: BookOpen, title: 'Explain how web caching works', prompt: 'Explain how an HTTP cache works using an everyday analogy.' },
];

const initialSession = () => `s-${Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('')}`;

function AssistantMessage({ reply, metadata }) {
  const cached = metadata.resolution_source === 'LLM_CACHE';
  const SourceIcon = cached ? Database : Zap;
  return (
    <article className="message assistant" data-testid="assistant-message">
      <div className="monogram message-avatar" aria-hidden="true">{assistantName[0]}</div>
      <div className="message-content">
        <div className="speaker">{assistantName}</div>
        <div className="reply"><Markdown remarkPlugins={[remarkGfm]} skipHtml>{reply}</Markdown></div>
        <div className="metadata" aria-label="Response metadata">
          <span className={`source ${cached ? 'cached' : ''}`}>
            <SourceIcon size={13} aria-hidden="true" />
            <span data-testid="meta-source">{metadata.resolution_source}</span>
          </span>
          <span title="Model" data-testid="meta-model">{metadata.model}</span>
          <span title="Server latency"><Clock3 size={14} aria-hidden="true" /><span data-testid="meta-latency">{metadata.latency_ms} ms</span></span>
          <span title="Input and output tokens">
            <span><span data-testid="meta-input-tokens">{metadata.input_tokens}</span> in</span>
            <span><span data-testid="meta-output-tokens">{metadata.output_tokens}</span> out</span>
          </span>
          {metadata.key_id && <span title="Provider key ID">{metadata.key_id}</span>}
          {metadata.fallback_attempts > 0 && <span>{metadata.fallback_attempts} {metadata.fallback_attempts === 1 ? 'fallback' : 'fallbacks'}</span>}
        </div>
      </div>
    </article>
  );
}

function SessionSettings({ dialog, value, onSave }) {
  const [draft, setDraft] = useState(value);

  function close() {
    dialog.current.close();
  }

  return (
    <dialog ref={dialog} aria-labelledby="settings-title" onClose={() => setDraft(value)}>
      <form onSubmit={(event) => { event.preventDefault(); onSave(draft.trim()); close(); }}>
        <div className="dialog-heading">
          <h2 id="settings-title">Session settings</h2>
          <button type="button" className="icon-button" aria-label="Close settings" onClick={close}><X size={20} /></button>
        </div>
        <label htmlFor="system-prompt">System prompt <span>Optional</span></label>
        <p id="prompt-hint">Set how {assistantName} should respond in this chat. Leave blank to use the default.</p>
        <textarea id="system-prompt" data-testid="system-prompt-input" aria-describedby="prompt-hint" value={draft} onChange={(event) => setDraft(event.target.value)} rows={5} placeholder="For example, keep answers concise and include examples." />
        <div className="dialog-actions">
          <button type="button" className="secondary-button" onClick={close}>Cancel</button>
          <button className="primary-button" type="submit">Save settings</button>
        </div>
      </form>
    </dialog>
  );
}

function App() {
  const [sessionId, setSessionId] = useState(initialSession);
  const [turns, setTurns] = useState([]);
  const [message, setMessage] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [sending, setSending] = useState(false);
  const [health, setHealth] = useState('checking');
  const input = useRef(null);
  const dialog = useRef(null);
  const scroller = useRef(null);
  const sendingRef = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    async function refresh() {
      try {
        await checkHealth(AbortSignal.any([controller.signal, AbortSignal.timeout(5000)]));
        if (!controller.signal.aborted) setHealth('online');
      } catch {
        if (!controller.signal.aborted) setHealth('offline');
      }
    }
    refresh();
    const interval = setInterval(refresh, 20_000);
    return () => { controller.abort(); clearInterval(interval); };
  }, []);

  useEffect(() => {
    if (turns.length && scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight;
  }, [turns]);

  function newSession() {
    setSessionId(initialSession());
    setTurns([]);
    setMessage('');
    setSystemPrompt('');
    input.current.focus();
  }

  async function submit() {
    const text = message.trim();
    if (!text || sendingRef.current) return;
    sendingRef.current = true;
    setSending(true);
    const id = turns.length;
    setTurns(previous => [...previous, { id, text }]);
    setMessage('');

    try {
      const result = await sendChat(sessionId, text, systemPrompt);
      setHealth('online');
      setTurns(previous => previous.map(turn => turn.id === id ? { ...turn, result } : turn));
    } catch (error) {
      setTurns(previous => previous.map(turn => turn.id === id ? { ...turn, error: error.message } : turn));
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  }

  function fill(text) {
    setMessage(text);
    input.current.focus();
  }

  return (
    <div className="workspace">
      <aside className="sidebar" aria-label="Workspace">
        <div className="brand"><span className="monogram brand-icon" aria-hidden="true">{assistantName[0]}</span><span>{assistantName}</span></div>
        <button className="new-chat" type="button" onClick={newSession} disabled={sending}>
          <Plus size={18} aria-hidden="true" /><span>New chat</span>
        </button>
        <div className="sidebar-session">
          <div className="sidebar-label">Current chat</div>
          <div className="session-item"><MessageCircle size={16} aria-hidden="true" /><span>{turns[0]?.text || 'Untitled chat'}</span></div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <h1>Conversation</h1>
          <div className="topbar-actions">
            <span role="status" className={`health ${health}`}><i />{health === 'online' ? 'API connected' : health === 'offline' ? 'API offline' : 'Checking API'}</span>
            <button className="settings-button" type="button" onClick={() => dialog.current.showModal()}>
              <SlidersHorizontal size={17} aria-hidden="true" /> <span>Settings</span>
            </button>
          </div>
        </header>

        <div ref={scroller} className="conversation-scroll">
          {turns.length === 0 ? (
            <section className="welcome content-width" aria-labelledby="welcome-title">
              <h2 id="welcome-title">How can I help?</h2>
              <div className="suggestions" role="group" aria-label="Suggested prompts">
                {suggestions.map(({ Icon, title, prompt }) => (
                  <button type="button" key={title} onClick={() => fill(prompt)}>
                    <Icon size={19} aria-hidden="true" /><span>{title}</span>
                  </button>
                ))}
              </div>
            </section>
          ) : (
            <div className="turns content-width" role="log" aria-label="Conversation messages" aria-relevant="additions text">
              {turns.map(({ id, text, result, error }) => (
                <section className="turn" key={id}>
                  <article className="message user">
                    <div className="message-content"><div className="speaker">You</div><div className="user-text">{text}</div></div>
                  </article>
                  {result && <AssistantMessage reply={result.reply} metadata={result.metadata} />}
                  {error && <div className="chat-error" role="alert"><AlertCircle size={18} aria-hidden="true" /><span>{error}</span><button type="button" disabled={sending} onClick={() => fill(text)}>Restore message</button></div>}
                  {!result && !error && <div className="pending" role="status"><span className="pending-dot" />Generating a reply…</div>}
                </section>
              ))}
            </div>
          )}
        </div>

        <div className="composer-area">
          <form className="content-width" onSubmit={(event) => { event.preventDefault(); submit(); }}>
            <div className="composer">
              <textarea
                ref={input} data-testid="chat-input" aria-label={`Message ${assistantName}`} placeholder={`Message ${assistantName}…`}
                rows={2} value={message} onChange={(event) => setMessage(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                    event.preventDefault();
                    event.currentTarget.form.requestSubmit();
                  }
                }}
              />
              <div className="composer-tools">
                {systemPrompt && <span className="prompt-active"><SlidersHorizontal size={14} aria-hidden="true" /> Custom system prompt</span>}
                <button className="send-button" type="submit" data-testid="send-button" aria-label="Send message" disabled={sending || !message.trim()}>Send</button>
              </div>
            </div>
            <div className="composer-hint"><span><kbd>Enter</kbd> to send</span><span><kbd>Shift</kbd> + <kbd>Enter</kbd> for a new line</span></div>
          </form>
        </div>
      </main>
      <SessionSettings key={sessionId} dialog={dialog} value={systemPrompt} onSave={setSystemPrompt} />
    </div>
  );
}

createRoot(document.getElementById('root')).render(<App />);
