import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from './App';
import { Dashboard } from './components/Dashboard';
import { VisitHistoryData, VisitHistoryPage } from './components/VisitHistoryPage';
import { DashboardData } from './fhir/types';
import './styles.css';

declare global {
  interface Window {
    __AGENTFORGE_PATIENT_DASHBOARD__?: DashboardData;
    __AGENTFORGE_VISIT_HISTORY__?: VisitHistoryData;
  }
}

const visitHistoryRoot = document.getElementById('agentforge-visit-history-root');
const root = visitHistoryRoot || document.getElementById('agentforge-modern-dashboard-root') || document.getElementById('root');
const bootstrappedData = window.__AGENTFORGE_PATIENT_DASHBOARD__;
const bootstrappedVisitHistory = window.__AGENTFORGE_VISIT_HISTORY__;

ReactDOM.createRoot(root as HTMLElement).render(
  <React.StrictMode>
    {visitHistoryRoot && bootstrappedVisitHistory ? (
      <VisitHistoryPage data={bootstrappedVisitHistory} />
    ) : bootstrappedData ? (
      <Dashboard data={bootstrappedData} embedded />
    ) : (
      <App />
    )}
  </React.StrictMode>
);
