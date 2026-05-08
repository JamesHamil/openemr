import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { App } from './App';

describe('modern dashboard app', () => {
  it('handles a SMART callback, selects patient context, and renders mocked FHIR data', async () => {
    window.history.pushState({}, '', '/interface/modules/custom_modules/agentforge/public/patient-dashboard/index.html?code=auth-code&state=demo-state');
    sessionStorage.setItem('agentforge.patientDashboard.clientId', 'demo-client');
    sessionStorage.setItem(
      'agentforge.patientDashboard.pkce',
      JSON.stringify({
        state: 'demo-state',
        verifier: 'pkce-verifier',
        redirectUri: `${window.location.origin}${window.location.pathname}`,
        fhirBaseUrl: 'https://openemr.test/apis/default/fhir',
      })
    );
    vi.stubGlobal('fetch', vi.fn((url: RequestInfo | URL) => Promise.resolve(mockFhirResponse(String(url)))));

    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Jordan Rivera' })).toBeInTheDocument();
    expect(screen.getByText('Penicillin')).toBeInTheDocument();
    expect(screen.getByText('Hypertension')).toBeInTheDocument();
    expect(screen.getAllByText('Metformin')).toHaveLength(2);
    expect(screen.getByText('Primary Care Team')).toBeInTheDocument();
    expect(screen.getByText('Follow-up')).toBeInTheDocument();
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('https://openemr.test/oauth2/default/token', expect.anything()));
  });
});

function mockFhirResponse(url: string) {
  const body = fhirPayload(url);
  return {
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  };
}

function fhirPayload(url: string) {
  if (url.includes('/.well-known/smart-configuration')) {
    return {
      authorization_endpoint: 'https://openemr.test/oauth2/default/authorize',
      token_endpoint: 'https://openemr.test/oauth2/default/token',
      issuer: 'https://openemr.test/apis/default/fhir',
    };
  }
  if (url.includes('/oauth2/default/token')) {
    return { access_token: 'token', patient: 'patient-123', expires_in: 3600 };
  }
  if (url.includes('/Patient/')) {
    return {
      resourceType: 'Patient',
      id: 'patient-123',
      active: true,
      birthDate: '1987-04-18',
      gender: 'female',
      name: [{ text: 'Jordan Rivera' }],
      identifier: [{ type: { text: 'MR' }, value: 'MRN-123' }],
    };
  }
  if (url.includes('/AllergyIntolerance')) {
    return bundle('AllergyIntolerance', { id: 'a1', code: { text: 'Penicillin' } });
  }
  if (url.includes('/Condition')) {
    return bundle('Condition', { id: 'c1', code: { text: 'Hypertension' } });
  }
  if (url.includes('/MedicationRequest')) {
    return bundle('MedicationRequest', {
      id: 'rx1',
      medicationCodeableConcept: { text: 'Metformin' },
      dosageInstruction: [{ text: 'Twice daily' }],
    });
  }
  if (url.includes('/Medication')) {
    return bundle('Medication', { id: 'm1', code: { text: 'Metformin' } });
  }
  if (url.includes('/CareTeam')) {
    return bundle('CareTeam', { id: 't1', name: 'Primary Care Team', participant: [{ member: { display: 'Dr. Chen' } }] });
  }
  if (url.includes('/Encounter')) {
    return bundle('Encounter', { id: 'e1', type: [{ text: 'Follow-up' }], period: { start: '2026-05-05' } });
  }
  return { resourceType: 'Bundle', entry: [] };
}

function bundle(resourceType: string, resource: object) {
  return { resourceType: 'Bundle', entry: [{ resource: { resourceType, ...resource } }] };
}
