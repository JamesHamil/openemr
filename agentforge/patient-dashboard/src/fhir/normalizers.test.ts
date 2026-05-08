import { describe, expect, it } from 'vitest';
import {
  normalizeAllergies,
  normalizeCareTeam,
  normalizeConditions,
  normalizeEncounters,
  normalizeMedicationRequests,
  normalizeMedications,
  normalizePatient,
} from './normalizers';

describe('FHIR normalizers', () => {
  it('normalizes patient identity for the dashboard header', () => {
    const patient = normalizePatient({
      resourceType: 'Patient',
      id: 'patient-1',
      active: true,
      birthDate: '1987-04-18',
      gender: 'female',
      name: [{ use: 'official', given: ['Jordan'], family: 'Rivera' }],
      identifier: [{ type: { text: 'MR' }, value: 'MRN-123' }],
    });

    expect(patient).toEqual({
      id: 'patient-1',
      name: 'Jordan Rivera',
      dateOfBirth: '1987-04-18',
      sex: 'Female',
      mrn: 'MRN-123',
      active: true,
    });
  });

  it('normalizes allergy resources', () => {
    const allergies = normalizeAllergies(bundle('AllergyIntolerance', {
      id: 'allergy-1',
      code: { text: 'Penicillin' },
      clinicalStatus: { text: 'active' },
      reaction: [{ manifestation: [{ text: 'Hives' }] }],
    }));

    expect(allergies[0]).toMatchObject({ id: 'allergy-1', title: 'Penicillin', status: 'active' });
  });

  it('normalizes problem list conditions', () => {
    const conditions = normalizeConditions(bundle('Condition', {
      id: 'condition-1',
      code: { coding: [{ display: 'Hypertension' }] },
      clinicalStatus: { text: 'active' },
    }));

    expect(conditions[0]).toMatchObject({ title: 'Hypertension', status: 'active' });
  });

  it('normalizes medication requests as prescriptions', () => {
    const requests = normalizeMedicationRequests(bundle('MedicationRequest', {
      id: 'rx-1',
      status: 'active',
      intent: 'order',
      authoredOn: '2026-05-05',
      medicationCodeableConcept: { text: 'Metformin 500 mg' },
      dosageInstruction: [{ text: 'Take twice daily' }],
    }));

    expect(requests[0]).toMatchObject({
      title: 'Metformin 500 mg',
      detail: 'Take twice daily',
      meta: '2026-05-05',
      status: 'active',
    });
  });

  it('normalizes medication resources and falls back to requests when empty', () => {
    const medications = normalizeMedications(bundle('Medication', {
      id: 'med-1',
      code: { text: 'Atorvastatin' },
    }));
    const fallback = normalizeMedications({ resourceType: 'Bundle', entry: [] }, bundle('MedicationRequest', {
      id: 'rx-2',
      medicationCodeableConcept: { text: 'Lisinopril' },
    }));

    expect(medications[0].title).toBe('Atorvastatin');
    expect(fallback[0].title).toBe('Lisinopril');
  });

  it('normalizes care team participants', () => {
    const careTeam = normalizeCareTeam(bundle('CareTeam', {
      id: 'team-1',
      name: 'Primary Care Team',
      status: 'active',
      participant: [{ member: { display: 'Dr. Chen' } }],
    }));

    expect(careTeam[0]).toMatchObject({ title: 'Primary Care Team', detail: 'Dr. Chen' });
  });

  it('normalizes encounters newest first', () => {
    const encounters = normalizeEncounters({
      resourceType: 'Bundle',
      entry: [
        { resource: { resourceType: 'Encounter', id: 'old', type: [{ text: 'Office visit' }], period: { start: '2026-01-01' } } },
        { resource: { resourceType: 'Encounter', id: 'new', type: [{ text: 'Follow-up' }], period: { start: '2026-05-01' } } },
      ],
    });

    expect(encounters.map((encounter) => encounter.id)).toEqual(['new', 'old']);
  });
});

function bundle(resourceType: string, resource: object) {
  return { resourceType: 'Bundle', entry: [{ resource: { resourceType, ...resource } }] };
}

