export interface FhirBundle<T = FhirResource> {
  resourceType: 'Bundle';
  entry?: Array<{ resource?: T }>;
}

export interface FhirResource {
  resourceType?: string;
  id?: string;
  [key: string]: unknown;
}

export interface PatientHeader {
  id: string;
  name: string;
  dateOfBirth: string;
  sex: string;
  mrn: string;
  active: boolean;
}

export interface ClinicalItem {
  id: string;
  title: string;
  detail?: string;
  meta?: string;
  status?: string;
}

export interface EncounterItem extends ClinicalItem {
  startDate: string;
  endDate?: string;
  provider?: string;
  dateSort: number;
  sourceType?: 'encounter' | 'document' | 'fhir';
  encounterId?: string;
  documentId?: string;
  reviewDate?: string;
}

export interface DashboardCard {
  id: string;
  title: string;
  state: LoadState<ClinicalItem[]> | LoadState<EncounterItem[]>;
  emptyMessage?: string;
  span?: 'wide' | 'full';
}

export interface DashboardSection {
  id: string;
  title?: string;
  cards: DashboardCard[];
}

export type LoadState<T> =
  | { status: 'loading' }
  | { status: 'loaded'; data: T }
  | { status: 'error'; message: string };

export interface DashboardData {
  patient: LoadState<PatientHeader>;
  allergies: LoadState<ClinicalItem[]>;
  conditions: LoadState<ClinicalItem[]>;
  medications: LoadState<ClinicalItem[]>;
  prescriptions: LoadState<ClinicalItem[]>;
  careTeam: LoadState<ClinicalItem[]>;
  encounters: LoadState<EncounterItem[]>;
  sections?: DashboardSection[];
}
