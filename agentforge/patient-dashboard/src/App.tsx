import { useEffect, useMemo, useState } from 'react';
import { clearStoredSession, completeOAuthCallback, getStoredSession, isOAuthCallback, startLogin } from './auth';
import { readRuntimeConfig } from './config';
import { Dashboard } from './components/Dashboard';
import { DashboardData } from './fhir/types';
import { loadDashboardData, loadingDashboardData } from './fhir/client';

type AppState =
  | { kind: 'setup'; message: string }
  | { kind: 'signed-out' }
  | { kind: 'loading'; data: DashboardData }
  | { kind: 'ready'; data: DashboardData }
  | { kind: 'error'; message: string };

export function App() {
  const config = useMemo(() => readRuntimeConfig(), []);
  const [state, setState] = useState<AppState>(() => {
    if (!config.clientId) {
      return { kind: 'setup', message: 'Register a SMART app and provide its client ID to launch the dashboard.' };
    }
    return { kind: 'loading', data: loadingDashboardData() };
  });

  useEffect(() => {
    if (!config.clientId) {
      return;
    }
    let cancelled = false;
    async function boot() {
      try {
        const session = isOAuthCallback() ? await completeOAuthCallback(config) : getStoredSession();
        if (!session) {
          setState({ kind: 'signed-out' });
          return;
        }
        setState({ kind: 'loading', data: loadingDashboardData() });
        const data = await loadDashboardData(session);
        if (!cancelled) {
          setState({ kind: 'ready', data });
        }
      } catch (error) {
        if (!cancelled) {
          setState({ kind: 'error', message: error instanceof Error ? error.message : 'Dashboard failed to load.' });
        }
      }
    }
    void boot();
    return () => {
      cancelled = true;
    };
  }, [config]);

  if (state.kind === 'setup') {
    return <SetupPanel message={state.message} />;
  }
  if (state.kind === 'signed-out') {
    return <LoginPanel onLogin={() => void startLogin(config).catch((error) => setState({ kind: 'error', message: error.message }))} />;
  }
  if (state.kind === 'error') {
    return <ErrorPanel message={state.message} onReset={() => { clearStoredSession(); setState({ kind: 'signed-out' }); }} />;
  }
  return <Dashboard data={state.data} onSignOut={() => { clearStoredSession(); setState({ kind: 'signed-out' }); }} />;
}

function SetupPanel({ message }: { message: string }) {
  return (
    <main className="center-panel">
      <h1>Modern Patient Dashboard</h1>
      <p>{message}</p>
      <code>?client_id=&lt;registered-smart-client-id&gt;</code>
    </main>
  );
}

function LoginPanel({ onLogin }: { onLogin: () => void }) {
  return (
    <main className="center-panel">
      <h1>Modern Patient Dashboard</h1>
      <p>Sign in with OpenEMR to select a patient and load dashboard data from the FHIR API.</p>
      <button className="af-dashboard-button" type="button" onClick={onLogin}>
        Sign in with OpenEMR
      </button>
    </main>
  );
}

function ErrorPanel({ message, onReset }: { message: string; onReset: () => void }) {
  return (
    <main className="center-panel center-panel--error">
      <h1>Dashboard unavailable</h1>
      <p>{message}</p>
      <button className="af-dashboard-button af-dashboard-button--secondary" type="button" onClick={onReset}>
        Start over
      </button>
    </main>
  );
}
