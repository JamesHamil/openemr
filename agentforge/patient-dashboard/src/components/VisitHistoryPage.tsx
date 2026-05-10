import { useEffect } from 'react';
import { EncounterCalendar } from './EncounterCalendar';
import { EncounterItem, LoadState } from '../fhir/types';

declare global {
  interface Window {
    restoreSession?: () => void;
  }
}

interface OpenEmrNavigationWindow extends Window {
  left_nav?: {
    setEncounter?: (date: string, encounterId: string, frameName: string) => void;
    loadFrame?: (target: string, frameName: string, url: string) => void;
  };
}

export interface VisitHistoryData {
  patient: {
    id: string;
    name: string;
    dateOfBirth: string;
    mrn: string;
  };
  encounters: LoadState<EncounterItem[]>;
  billingUrl?: string;
  documentBaseUrl?: string;
  encounterBaseUrl?: string;
}

export function VisitHistoryPage({ data }: { data: VisitHistoryData }) {
  useEffect(() => {
    document.title = 'Visit History';
  }, []);

  function reviewVisit(encounter: EncounterItem) {
    if (encounter.sourceType === 'encounter' && encounter.encounterId) {
      const parentWindow = window.parent as OpenEmrNavigationWindow;
      window.top?.restoreSession?.();
      parentWindow.left_nav?.setEncounter?.(
        encounter.reviewDate || encounter.startDate.slice(0, 10),
        encounter.encounterId,
        window.name
      );
      if (parentWindow.left_nav?.loadFrame) {
        parentWindow.left_nav.loadFrame(
          'enc2',
          window.name,
          `patient_file/encounter/encounter_top.php?set_encounter=${encodeURIComponent(encounter.encounterId)}`
        );
      } else if (data.encounterBaseUrl) {
        window.location.href = `${data.encounterBaseUrl}?set_encounter=${encodeURIComponent(encounter.encounterId)}`;
      }
      return;
    }

    if (encounter.sourceType === 'document' && encounter.documentId && data.documentBaseUrl) {
      const params = new URLSearchParams({
        doc_id: encounter.documentId,
        patient_id: data.patient.id,
      });
      window.top?.restoreSession?.();
      window.location.href = `${data.documentBaseUrl}?document&view&${params.toString()}`;
    }
  }

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
      <EncounterCalendar state={data.encounters} emptyMessage="No visits recorded." onReviewVisit={reviewVisit} />
    </main>
  );
}
