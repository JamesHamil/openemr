import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from './App';
import { Dashboard } from './components/Dashboard';
import { DashboardData } from './fhir/types';
import './styles.css';

declare global {
  interface Window {
    __AGENTFORGE_PATIENT_DASHBOARD__?: DashboardData;
  }
}

const root = document.getElementById('agentforge-modern-dashboard-root') || document.getElementById('root');
const bootstrappedData = window.__AGENTFORGE_PATIENT_DASHBOARD__;

ReactDOM.createRoot(root as HTMLElement).render(
  <React.StrictMode>
    {bootstrappedData ? <Dashboard data={bootstrappedData} embedded /> : <App />}
  </React.StrictMode>
);
