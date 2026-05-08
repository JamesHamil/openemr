import { ClinicalItem, EncounterItem, FhirBundle, FhirResource, PatientHeader } from './types';

export function bundleResources<T extends FhirResource>(payload: unknown, resourceType?: string): T[] {
  if (isBundle(payload)) {
    return (payload.entry || [])
      .map((entry) => entry.resource)
      .filter((resource): resource is T => Boolean(resource && (!resourceType || resource.resourceType === resourceType)));
  }
  if (isResource(payload) && (!resourceType || payload.resourceType === resourceType)) {
    return [payload as T];
  }
  return [];
}

export function normalizePatient(payload: unknown): PatientHeader {
  const patient = bundleResources<FhirResource>(payload, 'Patient')[0];
  if (!patient) {
    throw new Error('Patient resource was not returned.');
  }
  return {
    id: String(patient.id || ''),
    name: humanName(patient.name),
    dateOfBirth: stringValue(patient.birthDate) || 'Unknown DOB',
    sex: titleCase(stringValue(patient.gender) || 'unknown'),
    mrn: identifierValue(patient.identifier) || 'No MRN',
    active: Boolean(patient.active ?? true),
  };
}

export function normalizeAllergies(payload: unknown): ClinicalItem[] {
  return bundleResources<FhirResource>(payload, 'AllergyIntolerance').map((resource) => ({
    id: resourceId(resource),
    title: codeableText(resource.code) || 'Unnamed allergy',
    detail: codeableText(resource.reaction) || stringValue(resource.criticality) || 'Reaction details not recorded',
    meta: stringValue(resource.recordedDate) || stringValue(resource.onsetDateTime),
    status: clinicalStatus(resource),
  }));
}

export function normalizeConditions(payload: unknown): ClinicalItem[] {
  return bundleResources<FhirResource>(payload, 'Condition').map((resource) => ({
    id: resourceId(resource),
    title: codeableText(resource.code) || 'Unnamed problem',
    detail: codeableText(resource.category) || stringValue(resource.onsetDateTime),
    meta: stringValue(resource.recordedDate) || stringValue(resource.onsetDateTime),
    status: clinicalStatus(resource),
  }));
}

export function normalizeMedicationRequests(payload: unknown): ClinicalItem[] {
  return bundleResources<FhirResource>(payload, 'MedicationRequest').map((resource) => ({
    id: resourceId(resource),
    title: medicationTitle(resource),
    detail: dosageText(resource.dosageInstruction) || stringValue(resource.intent) || 'No dosage instructions recorded',
    meta: stringValue(resource.authoredOn) || requesterText(resource.requester),
    status: stringValue(resource.status) || 'unknown',
  }));
}

export function normalizeMedications(medicationPayload: unknown, requestPayload?: unknown): ClinicalItem[] {
  const medications = bundleResources<FhirResource>(medicationPayload, 'Medication').map((resource) => ({
    id: resourceId(resource),
    title: codeableText(resource.code) || 'Unnamed medication',
    detail: stringValue(resource.form) || 'Medication resource',
    status: stringValue(resource.status),
  }));
  if (medications.length) {
    return medications;
  }
  return normalizeMedicationRequests(requestPayload).map((request) => ({
    ...request,
    detail: request.detail || 'Medication listed from prescription request',
  }));
}

export function normalizeCareTeam(payload: unknown): ClinicalItem[] {
  return bundleResources<FhirResource>(payload, 'CareTeam').map((resource) => ({
    id: resourceId(resource),
    title: stringValue(resource.name) || 'Care team',
    detail: participantText(resource.participant) || 'Participants not recorded',
    meta: periodText(resource.period),
    status: stringValue(resource.status) || 'unknown',
  }));
}

export function normalizeEncounters(payload: unknown): EncounterItem[] {
  return bundleResources<FhirResource>(payload, 'Encounter')
    .map((resource) => {
      const start = periodStart(resource.period) || stringValue(resource.date);
      return {
        id: resourceId(resource),
        title: codeableText(resource.type) || codeableText(resource.class) || 'Encounter',
        detail: codeableText(resource.reasonCode) || stringValue(resource.serviceType) || 'Reason not recorded',
        meta: periodText(resource.period) || start,
        status: stringValue(resource.status) || 'unknown',
        dateSort: start ? Date.parse(start) || 0 : 0,
      };
    })
    .sort((left, right) => right.dateSort - left.dateSort);
}

function isBundle(payload: unknown): payload is FhirBundle {
  return isResource(payload) && payload.resourceType === 'Bundle' && Array.isArray(payload.entry);
}

function isResource(payload: unknown): payload is FhirResource {
  return Boolean(payload && typeof payload === 'object');
}

function resourceId(resource: FhirResource): string {
  return String(resource.id || crypto.randomUUID());
}

function humanName(value: unknown): string {
  if (!Array.isArray(value) || !value.length) {
    return 'Unnamed patient';
  }
  const preferred = value.find((name) => isResource(name) && name.use === 'official') || value[0];
  if (!isResource(preferred)) {
    return 'Unnamed patient';
  }
  const text = stringValue(preferred.text);
  if (text) {
    return text;
  }
  const given = Array.isArray(preferred.given) ? preferred.given.map(stringValue).filter(Boolean).join(' ') : '';
  return [given, stringValue(preferred.family)].filter(Boolean).join(' ') || 'Unnamed patient';
}

function identifierValue(value: unknown): string {
  if (!Array.isArray(value)) {
    return '';
  }
  const preferred = value.find((identifier) => isResource(identifier) && codeableText(identifier.type).toLowerCase().includes('mr'));
  const identifier = (preferred || value[0]) as FhirResource | undefined;
  return identifier ? stringValue(identifier.value) : '';
}

function codeableText(value: unknown): string {
  if (Array.isArray(value)) {
    return value.map(codeableText).filter(Boolean).join(', ');
  }
  if (!isResource(value)) {
    return stringValue(value);
  }
  const text = stringValue(value.text);
  if (text) {
    return text;
  }
  if (Array.isArray(value.coding)) {
    const coding = value.coding.find(isResource) as FhirResource | undefined;
    return stringValue(coding?.display) || stringValue(coding?.code);
  }
  return '';
}

function clinicalStatus(resource: FhirResource): string {
  return codeableText(resource.clinicalStatus) || stringValue(resource.status) || 'unknown';
}

function medicationTitle(resource: FhirResource): string {
  return (
    codeableText(resource.medicationCodeableConcept) ||
    referenceDisplay(resource.medicationReference) ||
    'Medication request'
  );
}

function dosageText(value: unknown): string {
  if (!Array.isArray(value)) {
    return '';
  }
  return value.map((item) => (isResource(item) ? stringValue(item.text) : '')).filter(Boolean).join('; ');
}

function requesterText(value: unknown): string {
  return referenceDisplay(value);
}

function participantText(value: unknown): string {
  if (!Array.isArray(value)) {
    return '';
  }
  return value
    .map((participant) => {
      if (!isResource(participant)) {
        return '';
      }
      return referenceDisplay(participant.member) || codeableText(participant.role);
    })
    .filter(Boolean)
    .join(', ');
}

function referenceDisplay(value: unknown): string {
  if (!isResource(value)) {
    return '';
  }
  return stringValue(value.display) || stringValue(value.reference);
}

function periodText(value: unknown): string {
  if (!isResource(value)) {
    return '';
  }
  const start = stringValue(value.start);
  const end = stringValue(value.end);
  if (start && end) {
    return `${start} to ${end}`;
  }
  return start || end;
}

function periodStart(value: unknown): string {
  return isResource(value) ? stringValue(value.start) : '';
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function titleCase(value: string): string {
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

