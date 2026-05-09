import { useEffect } from 'react';
import { EncounterCalendar } from './EncounterCalendar';
import { EncounterItem, LoadState } from '../fhir/types';

declare global {
  interface Window {
    restoreSession?: () => void;
  }
}

export interface VisitHistoryData {
  patient: {
    name: string;
    dateOfBirth: string;
    mrn: string;
  };
  encounters: LoadState<EncounterItem[]>;
  billingUrl?: string;
}

export function VisitHistoryPage({ data }: { data: VisitHistoryData }) {
  useEffect(() => {
    document.title = 'Visit History';
  }, []);

  return (
    <main className="af-dashboard-root af-visit-history-page">
      <div className="af-visit-history-page__toolbar">
        <div>
          <h1>Visit History</h1>
          <p>
            {data.patient.name} ({data.patient.mrn}) <span>DOB: {data.patient.dateOfBirth}</span>
          </p>
        </div>
        <div className="af-visit-history-page__actions">
          {data.billingUrl ? (
            <a className="af-dashboard-button af-dashboard-button--info" href={data.billingUrl} onClick={() => window.top?.restoreSession?.()}>
              To Billing View
            </a>
          ) : null}
          <button className="af-dashboard-button af-dashboard-button--secondary" type="button" onClick={() => window.print()}>
            Print page
          </button>
        </div>
      </div>
      <EncounterCalendar state={data.encounters} emptyMessage="No visits recorded." />
    </main>
  );
}
