import { FormEvent, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

export interface ClinicalCopilotConfig {
  authorized: boolean;
  patientId: string;
  encounterId: string;
  csrfToken: string;
  chatUrl: string;
  documentBaseUrl: string;
}

interface AgentForgeResponse {
  answer?: string;
  sections?: ResponseSection[];
  claims?: Claim[];
  sources?: Source[];
  warnings?: Warning[];
  verification_status?: string;
  trace_id?: string;
  debug_trace?: unknown;
}

interface ResponseSection {
  id?: string;
  title?: string;
  claim_ids?: string[];
}

interface Claim {
  id: string;
  text: string;
  source_ids?: string[];
}

interface Source {
  id?: string;
  record_type?: string;
  extracted_value?: string;
  field_path?: string;
  metadata?: Record<string, string>;
}

interface Warning {
  code?: string;
  message?: string;
}

type RequestState =
  | { kind: 'idle' }
  | { kind: 'loading'; phase: string; elapsed: number }
  | { kind: 'ready'; response: AgentForgeResponse }
  | { kind: 'error'; message: string };

const DEFAULT_PROMPT = 'Give me a chart brief for rounds.';
const PROMPTS = [
  DEFAULT_PROMPT,
  'What changed since the last visit?',
  'Summarize active problems and medications.',
  'What should I watch for during rounds?',
];

export function ClinicalCopilot({ config }: { config: ClinicalCopilotConfig }) {
  const [message, setMessage] = useState(DEFAULT_PROMPT);
  const [state, setState] = useState<RequestState>({ kind: 'idle' });

  const statusLabel = state.kind === 'loading'
    ? `${state.phase} ${state.elapsed}s`
    : state.kind === 'ready'
      ? state.response.verification_status || 'complete'
      : state.kind === 'error'
        ? 'failed'
        : 'Ready';

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    if (!config.authorized || !config.patientId) {
      return;
    }
    window.top?.restoreSession?.();

    const prompt = message.trim() || DEFAULT_PROMPT;
    const form = new URLSearchParams();
    form.set('csrf_token_form', config.csrfToken);
    form.set('patient_id', config.patientId);
    form.set('encounter_id', config.encounterId);
    form.set('conversation_id', `rounding-${config.patientId}`);
    form.set('message', prompt);
    form.set('stream', '1');

    let elapsed = 0;
    let phase = 'Starting request';
    setState({ kind: 'loading', phase, elapsed });
    const timer = window.setInterval(() => {
      elapsed += 1;
      setState({ kind: 'loading', phase, elapsed });
    }, 1000);

    const updatePhase = (nextPhase: string) => {
      phase = nextPhase || phase;
      setState({ kind: 'loading', phase, elapsed });
    };

    try {
      const response = await fetch(config.chatUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: form.toString(),
      });
      const contentType = response.headers.get('Content-Type') || '';
      if (!response.body || !contentType.includes('application/x-ndjson')) {
        setState({ kind: 'ready', response: await response.json() });
        return;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const chunk = await reader.read();
        if (chunk.value) {
          buffer += decoder.decode(chunk.value, { stream: !chunk.done });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';
          lines.forEach((line) => handleStreamLine(line, updatePhase, setState));
        }
        if (chunk.done) {
          break;
        }
      }
      if (buffer.trim()) {
        handleStreamLine(buffer, updatePhase, setState);
      }
    } catch {
      setState({ kind: 'error', message: 'Clinical Co-Pilot request failed before a verified response was returned.' });
    } finally {
      window.clearInterval(timer);
    }
  }

  return (
    <main className="af-dashboard-root af-copilot-page">
      <section className="af-copilot-shell" aria-label="Clinical Co-Pilot">
        <header className="af-copilot-hero">
          <div>
            <p className="af-dashboard-eyebrow">AgentForge</p>
            <h1>Clinical Co-Pilot</h1>
            <p>Read-only, source-backed chart brief for rounds.</p>
          </div>
          <span className={`af-copilot-status af-copilot-status--${statusTone(statusLabel)}`}>{statusLabel}</span>
        </header>

        {!config.authorized ? (
          <Notice tone="error" title="Access denied" message="You do not have permission to use Clinical Co-Pilot." />
        ) : !config.patientId ? (
          <Notice tone="warning" title="Open a patient chart" message="Open a patient chart before using Clinical Co-Pilot." />
        ) : (
          <div className="af-copilot-layout">
            <form className="af-copilot-prompt" onSubmit={submit}>
              <label htmlFor="agentforgeMessage">Question</label>
              <textarea
                id="agentforgeMessage"
                onChange={(event) => setMessage(event.target.value)}
                rows={5}
                value={message}
              />
              <div className="af-copilot-prompt__chips" aria-label="Prompt suggestions">
                {PROMPTS.map((prompt) => (
                  <button key={prompt} onClick={() => setMessage(prompt)} type="button">
                    {prompt}
                  </button>
                ))}
              </div>
              <button className="af-copilot-primary" disabled={state.kind === 'loading'} type="submit">
                {state.kind === 'loading' ? 'Generating...' : 'Generate Brief'}
              </button>
            </form>

            <ResponsePanel state={state} />
            <EvidencePanel config={config} response={state.kind === 'ready' ? state.response : undefined} />
          </div>
        )}
      </section>
    </main>
  );
}

function ResponsePanel({ state }: { state: RequestState }) {
  if (state.kind === 'idle') {
    return (
      <section className="af-copilot-response">
        <p className="af-dashboard-eyebrow">Verified Response</p>
        <div className="af-copilot-empty">The verified response will appear here.</div>
      </section>
    );
  }
  if (state.kind === 'loading') {
    return (
      <section className="af-copilot-response">
        <p className="af-dashboard-eyebrow">Working</p>
        <div className="af-copilot-progress">
          <strong>{state.phase}</strong>
          <span>Waiting for the verified, source-backed response ({state.elapsed}s).</span>
        </div>
      </section>
    );
  }
  if (state.kind === 'error') {
    return (
      <section className="af-copilot-response af-copilot-response--error">
        <p className="af-dashboard-eyebrow">Request Failed</p>
        <div className="af-copilot-empty">{state.message}</div>
      </section>
    );
  }

  const claimsById = new Map((state.response.claims || []).map((claim) => [claim.id, claim]));
  const sections = state.response.sections || [];
  const answerCitationIds = citationIdsForResponse(state.response);

  return (
    <section className="af-copilot-response">
      <div className="af-copilot-response__header">
        <p className="af-dashboard-eyebrow">Verified Response</p>
        <span>{state.response.verification_status || 'complete'}</span>
      </div>
      {state.response.answer ? (
        <div className="af-copilot-answer">
          <p>{state.response.answer}</p>
          <CitationLinks sourceIds={answerCitationIds} />
        </div>
      ) : null}
      {sections.length ? (
        <div className="af-copilot-sections">
          {sections.map((section) => {
            const claims = (section.claim_ids || []).map((id) => claimsById.get(id)).filter((claim): claim is Claim => Boolean(claim));
            if (!claims.length) {
              return null;
            }
            return (
              <article className="af-copilot-section" key={section.id || section.title}>
                <h2>{section.title || titleize(section.id || 'Summary')}</h2>
                <ul>
                  {claims.map((claim) => (
                    <li key={claim.id}>
                      <span>{claim.text}</span>
                      <CitationLinks sourceIds={claim.source_ids || []} compact />
                    </li>
                  ))}
                </ul>
              </article>
            );
          })}
        </div>
      ) : !state.response.answer ? (
        <div className="af-copilot-empty">No response body returned.</div>
      ) : null}
    </section>
  );
}

function CitationLinks({ sourceIds, compact = false }: { sourceIds: string[]; compact?: boolean }) {
  const uniqueIds = unique(sourceIds.filter(Boolean));
  if (!uniqueIds.length) {
    return null;
  }

  return (
    <div className={compact ? 'af-copilot-citations af-copilot-citations--compact' : 'af-copilot-citations'} aria-label="Citations">
      {!compact ? <span>Citations</span> : null}
      {uniqueIds.map((sourceId) => (
        <a href={`#${sourceAnchorId(sourceId)}`} key={sourceId}>
          [{sourceId}]
        </a>
      ))}
    </div>
  );
}

function EvidencePanel({ config, response }: { config: ClinicalCopilotConfig; response?: AgentForgeResponse }) {
  const sourceGroups = useMemo(() => groupSources(response?.sources || []), [response]);
  return (
    <section className="af-copilot-evidence" aria-label="Evidence and trace">
      <EvidenceBox title="Sources" count={response?.sources?.length || 0}>
        {Object.entries(sourceGroups).map(([group, sources]) => (
          <div className="af-copilot-source-group" key={group}>
            <h3>{group}</h3>
            <ul>
              {sources.map((source) => (
                <li id={source.id ? sourceAnchorId(source.id) : undefined} key={source.id || source.extracted_value}>
                  <strong>{source.id || 'source'}</strong>
                  <span>{source.extracted_value || 'No value recorded'}</span>
                  {sourceMetadata(source) ? <small>{sourceMetadata(source)}</small> : null}
                  {documentSourceUrl(config, source) ? (
                    <a href={documentSourceUrl(config, source)} rel="noopener noreferrer" target="_blank">Open document</a>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ))}
        {!response?.sources?.length ? <div className="af-copilot-muted">None yet.</div> : null}
      </EvidenceBox>

      <EvidenceBox title="Warnings" count={response?.warnings?.length || 0}>
        {response?.warnings?.length ? (
          <ul className="af-copilot-simple-list">
            {response.warnings.map((warning) => (
              <li key={`${warning.code}-${warning.message}`}>
                <strong>{warning.code || 'warning'}</strong>
                <span>{warning.message || ''}</span>
              </li>
            ))}
          </ul>
        ) : (
          <div className="af-copilot-muted">None.</div>
        )}
      </EvidenceBox>

      <EvidenceBox title="Trace" count={response?.trace_id ? 1 : 0}>
        {response?.trace_id ? (
          <details className="af-copilot-trace">
            <summary>{response.trace_id}</summary>
            {response.debug_trace ? <pre>{JSON.stringify(response.debug_trace, null, 2)}</pre> : null}
          </details>
        ) : (
          <div className="af-copilot-muted">Trace appears after a request.</div>
        )}
      </EvidenceBox>
    </section>
  );
}

function EvidenceBox({ title, count, children }: { title: string; count: number; children: ReactNode }) {
  return (
    <article className="af-copilot-evidence-box">
      <header>
        <h2>{title}</h2>
        <span>{count}</span>
      </header>
      <div>{children}</div>
    </article>
  );
}

function Notice({ tone, title, message }: { tone: 'error' | 'warning'; title: string; message: string }) {
  return (
    <div className={`af-copilot-notice af-copilot-notice--${tone}`}>
      <strong>{title}</strong>
      <p>{message}</p>
    </div>
  );
}

function handleStreamLine(
  line: string,
  updatePhase: (phase: string) => void,
  setState: (state: RequestState) => void
) {
  if (!line.trim()) {
    return;
  }
  try {
    const event = JSON.parse(line);
    if (event.schema_version === 'agentforge.response.v1') {
      setState({ kind: 'ready', response: event });
      return;
    }
    const payload = event.payload || {};
    if (event.event === 'progress') {
      updatePhase(payload.message || 'Working');
      return;
    }
    if (event.event === 'final' || event.event === 'error') {
      setState({ kind: 'ready', response: payload });
    }
  } catch {
    // Ignore malformed stream fragments.
  }
}

function groupSources(sources: Source[]): Record<string, Source[]> {
  return sources.reduce<Record<string, Source[]>>((groups, source) => {
    const group = sourceGroup(source);
    groups[group] = groups[group] || [];
    groups[group].push(source);
    return groups;
  }, {});
}

function sourceGroup(source: Source): string {
  if (source.record_type === 'guideline' || source.metadata?.source_kind === 'guideline') {
    return 'Guidelines';
  }
  if (source.record_type === 'document_fact' || source.metadata?.source_kind === 'document_extraction') {
    return 'Extracted Documents';
  }
  return 'Patient Chart';
}

function sourceMetadata(source: Source): string {
  const metadata = source.metadata || {};
  if (sourceGroup(source) === 'Guidelines') {
    return [metadata.title, metadata.section, metadata.citation_label].filter(Boolean).join(' | ');
  }
  if (sourceGroup(source) === 'Extracted Documents') {
    const citation = parseCitation(metadata.citation || '');
    return [
      metadata.filename,
      citation.page_or_section,
      citation.field_or_chunk_id,
      citation.quote_or_value ? `"${citation.quote_or_value}"` : '',
    ].filter(Boolean).join(' | ');
  }
  return source.field_path || '';
}

function parseCitation(raw: string): Record<string, string> {
  if (!raw) {
    return {};
  }
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

function documentSourceUrl(config: ClinicalCopilotConfig, source: Source): string {
  const documentId = source.metadata?.openemr_document_id || '';
  if (!documentId || !config.patientId) {
    return '';
  }
  return `${config.documentBaseUrl}?document&view&patient_id=${encodeURIComponent(config.patientId)}&doc_id=${encodeURIComponent(documentId)}`;
}

function citationIdsForResponse(response: AgentForgeResponse): string[] {
  const sourceIds = (response.sources || []).map((source) => source.id || '').filter(Boolean);
  const citedByClaims = (response.claims || []).flatMap((claim) => claim.source_ids || []);
  const citedInAnswer = extractBracketedCitationIds(response.answer || '').filter((sourceId) => sourceIds.includes(sourceId));
  const preferred = unique([...citedByClaims, ...citedInAnswer]);
  if (preferred.length) {
    return preferred;
  }
  return sourceIds.length <= 5 ? sourceIds : [];
}

function extractBracketedCitationIds(answer: string): string[] {
  const matches = answer.matchAll(/\[([^\]]+)\]/g);
  return Array.from(matches).flatMap((match) => match[1].split(',').map((sourceId) => sourceId.trim()));
}

function unique(values: string[]): string[] {
  return Array.from(new Set(values));
}

function sourceAnchorId(sourceId: string): string {
  return `af-source-${sourceId.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
}

function statusTone(status: string): string {
  const normalized = status.toLowerCase();
  if (normalized.includes('failed') || normalized.includes('refused')) {
    return 'error';
  }
  if (normalized.includes('verified') || normalized === 'ready') {
    return 'ready';
  }
  return 'working';
}

function titleize(value: string): string {
  return value.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}
