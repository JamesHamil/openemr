import { ClinicalCard, ClinicalListItem } from './ClinicalCard';
import { PatientHeader } from './PatientHeader';
import { DashboardCard, DashboardData, DashboardSection } from '../fhir/types';

export function Dashboard({ data, embedded = false, onSignOut }: { data: DashboardData; embedded?: boolean; onSignOut?: () => void }) {
  const sections = data.sections || defaultSections(data, embedded);

  return (
    <main className="af-dashboard-root af-dashboard-shell">
      <div className="af-dashboard-toolbar">
        <div>
          <strong>AgentForge</strong>
          <span>{embedded ? 'Modernized OpenEMR dashboard' : 'FHIR-backed modern dashboard'}</span>
        </div>
        {!embedded && onSignOut ? (
          <button className="af-dashboard-button af-dashboard-button--secondary" type="button" onClick={onSignOut}>
            Sign out
          </button>
        ) : null}
      </div>
      <PatientHeader state={data.patient} />
      {sections.map((section) => (
        <DashboardSectionView key={section.id} section={section} />
      ))}
    </main>
  );
}

function DashboardSectionView({ section }: { section: DashboardSection }) {
  return (
    <section className="af-dashboard-section" aria-label={section.title || 'Dashboard section'}>
      {section.title ? <h2 className="af-dashboard-section__title">{section.title}</h2> : null}
      <div className="af-dashboard-grid">
        {section.cards.map((card) => (
          <DashboardCardView key={card.id} card={card} />
        ))}
      </div>
    </section>
  );
}

function DashboardCardView({ card }: { card: DashboardCard }) {
  const spanClass = card.span ? `af-dashboard-card--${card.span}` : '';
  return (
    <ClinicalCard
      title={card.title}
      state={card.state}
      emptyMessage={card.emptyMessage || 'Nothing recorded.'}
      className={spanClass}
      renderItem={(item) => <ClinicalListItem item={item} />}
    />
  );
}

function defaultSections(data: DashboardData, embedded: boolean): DashboardSection[] {
  const emptySource = embedded ? 'recorded' : 'returned by FHIR';
  return [
    {
      id: 'clinical-summary',
      cards: [
        { id: 'allergies', title: 'Allergies', state: data.allergies, emptyMessage: `No active allergies ${emptySource}.` },
        { id: 'conditions', title: 'Problem List', state: data.conditions, emptyMessage: `No active problems ${emptySource}.` },
        { id: 'medications', title: 'Medications', state: data.medications, emptyMessage: `No medications ${emptySource}.` },
        { id: 'prescriptions', title: 'Prescriptions', state: data.prescriptions, emptyMessage: `No prescriptions ${emptySource}.`, span: 'full' },
      ],
    },
    {
      id: 'care-context',
      cards: [
        { id: 'care-team', title: 'Care Team', state: data.careTeam, emptyMessage: `No care team entries ${emptySource}.` },
        { id: 'encounters', title: 'Encounter History', state: data.encounters, emptyMessage: `No encounters ${emptySource}.` },
      ],
    },
  ];
}
