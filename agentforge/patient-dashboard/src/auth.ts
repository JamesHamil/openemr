import { RuntimeConfig, fhirBaseUrl, smartConfigurationUrl } from './config';

const AUTH_KEY = 'agentforge.patientDashboard.auth';
const PKCE_KEY = 'agentforge.patientDashboard.pkce';

export interface SmartConfiguration {
  authorization_endpoint: string;
  token_endpoint: string;
  issuer?: string;
}

export interface AuthSession {
  accessToken: string;
  patientId: string;
  fhirBaseUrl: string;
  expiresAt: number;
}

interface PkceState {
  state: string;
  verifier: string;
  redirectUri: string;
  fhirBaseUrl: string;
}

export function isOAuthCallback(): boolean {
  const params = new URLSearchParams(window.location.search);
  return params.has('code') && params.has('state');
}

export function getStoredSession(): AuthSession | null {
  const raw = sessionStorage.getItem(AUTH_KEY);
  if (!raw) {
    return null;
  }
  try {
    const session = JSON.parse(raw) as AuthSession;
    if (!session.accessToken || !session.patientId || Date.now() >= session.expiresAt) {
      return null;
    }
    return session;
  } catch {
    return null;
  }
}

export function clearStoredSession(): void {
  sessionStorage.removeItem(AUTH_KEY);
  sessionStorage.removeItem(PKCE_KEY);
}

export async function startLogin(config: RuntimeConfig): Promise<void> {
  const discovery = await fetchSmartConfiguration(config);
  const verifier = randomString(64);
  const state = randomString(32);
  const redirectUri = redirectUriForCurrentPage();
  const challenge = await sha256Base64Url(verifier);
  const base = discovery.issuer || fhirBaseUrl(config);
  const pkceState: PkceState = { state, verifier, redirectUri, fhirBaseUrl: base };
  sessionStorage.setItem(PKCE_KEY, JSON.stringify(pkceState));

  const authorize = new URL(discovery.authorization_endpoint);
  authorize.searchParams.set('response_type', 'code');
  authorize.searchParams.set('client_id', config.clientId);
  authorize.searchParams.set('redirect_uri', redirectUri);
  authorize.searchParams.set('scope', config.scope);
  authorize.searchParams.set('aud', base);
  authorize.searchParams.set('state', state);
  authorize.searchParams.set('code_challenge', challenge);
  authorize.searchParams.set('code_challenge_method', 'S256');
  window.location.assign(authorize.toString());
}

export async function completeOAuthCallback(config: RuntimeConfig): Promise<AuthSession> {
  const params = new URLSearchParams(window.location.search);
  const error = params.get('error');
  if (error) {
    throw new Error(params.get('error_description') || error);
  }
  const code = params.get('code');
  const state = params.get('state');
  const pkceState = readPkceState();
  if (!code || !state || state !== pkceState.state) {
    throw new Error('SMART login state could not be verified.');
  }

  const discovery = await fetchSmartConfiguration(config);
  const form = new URLSearchParams();
  form.set('grant_type', 'authorization_code');
  form.set('code', code);
  form.set('redirect_uri', pkceState.redirectUri);
  form.set('client_id', config.clientId);
  form.set('code_verifier', pkceState.verifier);

  const response = await fetch(discovery.token_endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: form.toString(),
  });
  if (!response.ok) {
    throw new Error(`SMART token exchange failed (${response.status}).`);
  }
  const token = await response.json();
  const accessToken = String(token.access_token || '');
  const patientId = String(token.patient || '');
  if (!accessToken || !patientId) {
    throw new Error('SMART token response did not include an access token and patient context.');
  }

  const expiresIn = Number(token.expires_in || 3600);
  const session: AuthSession = {
    accessToken,
    patientId,
    fhirBaseUrl: pkceState.fhirBaseUrl || discovery.issuer || fhirBaseUrl(config),
    expiresAt: Date.now() + Math.max(60, expiresIn - 30) * 1000,
  };
  sessionStorage.setItem(AUTH_KEY, JSON.stringify(session));
  sessionStorage.removeItem(PKCE_KEY);
  window.history.replaceState({}, document.title, redirectUriForCurrentPage());
  return session;
}

async function fetchSmartConfiguration(config: RuntimeConfig): Promise<SmartConfiguration> {
  const response = await fetch(smartConfigurationUrl(config));
  if (!response.ok) {
    throw new Error(`Unable to load SMART configuration (${response.status}).`);
  }
  const discovery = (await response.json()) as SmartConfiguration;
  if (!discovery.authorization_endpoint || !discovery.token_endpoint) {
    throw new Error('SMART configuration is missing OAuth endpoints.');
  }
  return discovery;
}

function readPkceState(): PkceState {
  const raw = sessionStorage.getItem(PKCE_KEY);
  if (!raw) {
    throw new Error('SMART login state was not found.');
  }
  return JSON.parse(raw) as PkceState;
}

function redirectUriForCurrentPage(): string {
  return `${window.location.origin}${window.location.pathname}`;
}

function randomString(length: number): string {
  const bytes = new Uint8Array(length);
  window.crypto.getRandomValues(bytes);
  return base64Url(bytes).slice(0, length);
}

async function sha256Base64Url(value: string): Promise<string> {
  const input = new TextEncoder().encode(value);
  const digest = await window.crypto.subtle.digest('SHA-256', input);
  return base64Url(new Uint8Array(digest));
}

function base64Url(bytes: Uint8Array): string {
  let binary = '';
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

