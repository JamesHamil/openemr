import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from './App';
import { ClinicalCopilot, ClinicalCopilotConfig } from './components/ClinicalCopilot';
import { Dashboard } from './components/Dashboard';
import { VisitHistoryData, VisitHistoryPage } from './components/VisitHistoryPage';
import { DashboardData } from './fhir/types';
import './styles.css';

declare global {
  interface Window {
    __AGENTFORGE_PATIENT_DASHBOARD__?: DashboardData;
    __AGENTFORGE_VISIT_HISTORY__?: VisitHistoryData;
    __AGENTFORGE_COPILOT__?: ClinicalCopilotConfig;
  }
}

const copilotRoot = document.getElementById('agentforge-copilot-root');
const visitHistoryRoot = document.getElementById('agentforge-visit-history-root');
const root = copilotRoot || visitHistoryRoot || document.getElementById('agentforge-modern-dashboard-root') || document.getElementById('root');
const bootstrappedData = window.__AGENTFORGE_PATIENT_DASHBOARD__;
const bootstrappedVisitHistory = window.__AGENTFORGE_VISIT_HISTORY__;
const bootstrappedCopilot = window.__AGENTFORGE_COPILOT__;

ReactDOM.createRoot(root as HTMLElement).render(
  <React.StrictMode>
    {copilotRoot && bootstrappedCopilot ? (
      <ClinicalCopilot config={bootstrappedCopilot} />
    ) : visitHistoryRoot && bootstrappedVisitHistory ? (
      <VisitHistoryPage data={bootstrappedVisitHistory} />
    ) : bootstrappedData ? (
      <Dashboard data={bootstrappedData} embedded />
    ) : (
      <App />
    )}
  </React.StrictMode>
);
