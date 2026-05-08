import { ReactNode } from 'react';
import { ClinicalItem, LoadState } from '../fhir/types';

interface ClinicalCardProps<T extends ClinicalItem> {
  title: string;
  state: LoadState<T[]>;
  emptyMessage: string;
  className?: string;
  renderItem?: (item: T) => ReactNode;
}

export function ClinicalCard<T extends ClinicalItem>({ title, state, emptyMessage, className = '', renderItem }: ClinicalCardProps<T>) {
  return (
    <section className={`af-dashboard-card ${className}`.trim()} aria-label={title}>
      <div className="af-dashboard-card__header">
        <h2>{title}</h2>
        {state.status === 'loaded' ? <span>{state.data.length}</span> : null}
      </div>
      {state.status === 'loading' ? <CardMessage label="Loading" /> : null}
      {state.status === 'error' ? <CardMessage label={state.message} tone="error" /> : null}
      {state.status === 'loaded' && state.data.length === 0 ? <CardMessage label={emptyMessage} /> : null}
      {state.status === 'loaded' && state.data.length > 0 ? (
        <ul className="af-clinical-list">
          {state.data.map((item) => (
            <li key={item.id}>{renderItem ? renderItem(item) : <ClinicalListItem item={item} />}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

export function ClinicalListItem({ item }: { item: ClinicalItem }) {
  return (
    <article className="af-clinical-item">
      <div className="af-clinical-item__title">{item.title}</div>
      {item.detail ? <div className="af-clinical-item__detail">{item.detail}</div> : null}
      <div className="af-clinical-item__meta">
        {item.status ? <span>{item.status}</span> : null}
        {item.meta ? <span>{item.meta}</span> : null}
      </div>
    </article>
  );
}

function CardMessage({ label, tone = 'muted' }: { label: string; tone?: 'muted' | 'error' }) {
  return <div className={`af-dashboard-card__message af-dashboard-card__message--${tone}`}>{label}</div>;
}
