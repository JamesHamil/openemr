export const DEFAULT_SITE = 'default';

export const SMART_SCOPES = [
  'openid',
  'fhirUser',
  'launch/patient',
  'online_access',
  'api:fhir',
  'patient/Patient.rs',
  'patient/AllergyIntolerance.rs',
  'patient/Condition.rs',
  'patient/Medication.read',
  'patient/MedicationRequest.rs',
  'patient/CareTeam.rs',
  'patient/Encounter.rs',
];

export interface RuntimeConfig {
  baseUrl: string;
  site: string;
  clientId: string;
  scope: string;
}

export function readRuntimeConfig(): RuntimeConfig {
  const params = new URLSearchParams(window.location.search);
  const queryClientId = params.get('client_id') || '';
  if (queryClientId) {
    sessionStorage.setItem('agentforge.patientDashboard.clientId', queryClientId);
  }

  const envBase = import.meta.env.VITE_OPENEMR_BASE_URL || '';
  const envSite = import.meta.env.VITE_OPENEMR_SITE || '';
  const envClientId = import.meta.env.VITE_OPENEMR_CLIENT_ID || '';
  const envScope = import.meta.env.VITE_OPENEMR_SCOPE || '';
  const storedClientId = sessionStorage.getItem('agentforge.patientDashboard.clientId') || '';

  return {
    baseUrl: String(envBase || window.location.origin).replace(/\/$/, ''),
    site: String(envSite || DEFAULT_SITE),
    clientId: String(queryClientId || storedClientId || envClientId),
    scope: String(envScope || SMART_SCOPES.join(' ')),
  };
}

export function fhirBaseUrl(config: RuntimeConfig): string {
  return `${config.baseUrl}/apis/${encodeURIComponent(config.site)}/fhir`;
}

export function smartConfigurationUrl(config: RuntimeConfig): string {
  return `${fhirBaseUrl(config)}/.well-known/smart-configuration`;
}
