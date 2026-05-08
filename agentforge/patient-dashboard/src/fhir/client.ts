import { AuthSession } from '../auth';
import {
  normalizeAllergies,
  normalizeCareTeam,
  normalizeConditions,
  normalizeEncounters,
  normalizeMedicationRequests,
  normalizeMedications,
  normalizePatient,
} from './normalizers';
import { ClinicalItem, DashboardData, EncounterItem, LoadState, PatientHeader } from './types';

export async function loadDashboardData(session: AuthSession): Promise<DashboardData> {
  const client = new FhirClient(session);
  const medicationRequests = await loadSection(() => client.search('MedicationRequest'));
  const medicationReferences = medicationRequests.status === 'loaded' ? medicationReferencesFrom(medicationRequests.data) : [];

  const [patient, allergies, conditions, medicationBundle, careTeam, encounters] = await Promise.all([
    loadSection(() => client.readPatient()),
    loadSection(() => client.search('AllergyIntolerance')),
    loadSection(() => client.search('Condition')),
    loadSection(() => client.loadMedicationResources(medicationReferences)),
    loadSection(() => client.search('CareTeam')),
    loadSection(() => client.search('Encounter')),
  ]);

  return {
    patient: mapLoaded(patient, normalizePatient),
    allergies: mapLoaded(allergies, normalizeAllergies),
    conditions: mapLoaded(conditions, normalizeConditions),
    medications: mapLoaded(medicationBundle, (bundle) =>
      normalizeMedications(bundle, medicationRequests.status === 'loaded' ? medicationRequests.data : undefined)
    ),
    prescriptions: mapLoaded(medicationRequests, normalizeMedicationRequests),
    careTeam: mapLoaded(careTeam, normalizeCareTeam),
    encounters: mapLoaded(encounters, normalizeEncounters),
  };
}

class FhirClient {
  constructor(private readonly session: AuthSession) {}

  readPatient(): Promise<unknown> {
    return this.fetchJson(`Patient/${encodeURIComponent(this.session.patientId)}`);
  }

  search(resourceType: string): Promise<unknown> {
    const params = new URLSearchParams({ patient: this.session.patientId });
    return this.fetchJson(`${resourceType}?${params.toString()}`);
  }

  async loadMedicationResources(references: string[]): Promise<unknown> {
    if (!references.length) {
      return this.search('Medication');
    }
    const resources = await Promise.all(
      references.map((reference) =>
        this.fetchJson(reference.replace(/^\//, '')).catch(() => null)
      )
    );
    return {
      resourceType: 'Bundle',
      entry: resources.filter(Boolean).map((resource) => ({ resource })),
    };
  }

  private async fetchJson(path: string): Promise<unknown> {
    const url = new URL(path, `${this.session.fhirBaseUrl.replace(/\/$/, '')}/`);
    const response = await fetch(url.toString(), {
      headers: {
        Accept: 'application/fhir+json, application/json',
        Authorization: `Bearer ${this.session.accessToken}`,
      },
    });
    if (!response.ok) {
      throw new Error(`${url.pathname} failed with ${response.status}`);
    }
    return response.json();
  }
}

async function loadSection<T>(loader: () => Promise<T>): Promise<LoadState<T>> {
  try {
    return { status: 'loaded', data: await loader() };
  } catch (error) {
    return { status: 'error', message: error instanceof Error ? error.message : 'Unable to load data' };
  }
}

function mapLoaded<T, U>(state: LoadState<T>, mapper: (value: T) => U): LoadState<U> {
  if (state.status !== 'loaded') {
    return state;
  }
  try {
    return { status: 'loaded', data: mapper(state.data) };
  } catch (error) {
    return { status: 'error', message: error instanceof Error ? error.message : 'Unable to normalize data' };
  }
}

function medicationReferencesFrom(state: unknown): string[] {
  if (!state || typeof state !== 'object' || !('entry' in state) || !Array.isArray(state.entry)) {
    return [];
  }
  return state.entry
    .map((entry) => {
      const resource = entry && typeof entry === 'object' && 'resource' in entry ? entry.resource : null;
      if (!resource || typeof resource !== 'object' || !('medicationReference' in resource)) {
        return '';
      }
      const reference = resource.medicationReference;
      return reference && typeof reference === 'object' && 'reference' in reference
        ? String(reference.reference || '')
        : '';
    })
    .filter((reference): reference is string => reference.startsWith('Medication/'));
}

export function loadingDashboardData(): DashboardData {
  const loading = { status: 'loading' } as const;
  return {
    patient: loading,
    allergies: loading,
    conditions: loading,
    medications: loading,
    prescriptions: loading,
    careTeam: loading,
    encounters: loading,
    sections: [],
  };
}

export type DashboardLoadedLists = ClinicalItem[] | EncounterItem[] | PatientHeader;
