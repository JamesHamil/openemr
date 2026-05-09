import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ClinicalCard } from './ClinicalCard';
import { Dashboard } from './Dashboard';
import { DashboardData } from '../fhir/types';

describe('clinical cards', () => {
  it('renders loading, empty, error, and loaded states', () => {
    const { rerender } = render(<ClinicalCard title="Allergies" state={{ status: 'loading' }} emptyMessage="No allergies" />);
    expect(screen.getByText('Loading')).toBeInTheDocument();

    rerender(<ClinicalCard title="Allergies" state={{ status: 'loaded', data: [] }} emptyMessage="No allergies" />);
    expect(screen.getByText('No allergies')).toBeInTheDocument();

    rerender(<ClinicalCard title="Allergies" state={{ status: 'error', message: 'Unauthorized' }} emptyMessage="No allergies" />);
    expect(screen.getByText('Unauthorized')).toBeInTheDocument();

    rerender(
      <ClinicalCard
        title="Allergies"
        state={{ status: 'loaded', data: [{ id: 'a1', title: 'Penicillin', status: 'active' }] }}
        emptyMessage="No allergies"
      />
    );
    expect(screen.getByText('Penicillin')).toBeInTheDocument();
    expect(screen.getByText('active')).toBeInTheDocument();
  });
});

describe('dashboard', () => {
  it('renders patient header and all required cards', () => {
    render(<Dashboard data={dashboardData()} onSignOut={vi.fn()} />);

    expect(screen.getByRole('heading', { name: 'Jordan Rivera' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Allergies' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Problem List' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Medications' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Prescriptions' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Care Team' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Visit History' })).toBeInTheDocument();
    expect(screen.getByText('May 2026')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Day' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Week' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Month' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'All' })).toBeInTheDocument();
    expect(screen.getByText('Visits on May 5, 2026')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Demographics' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Appointments' })).toBeInTheDocument();
  });
});

function dashboardData(): DashboardData {
  return {
    patient: {
      status: 'loaded',
      data: { id: 'p1', name: 'Jordan Rivera', dateOfBirth: '1987-04-18', sex: 'Female', mrn: 'MRN-123', active: true },
    },
    allergies: { status: 'loaded', data: [{ id: 'a1', title: 'Penicillin' }] },
    conditions: { status: 'loaded', data: [{ id: 'c1', title: 'Hypertension' }] },
    medications: { status: 'loaded', data: [{ id: 'm1', title: 'Metformin' }] },
    prescriptions: { status: 'loaded', data: [{ id: 'r1', title: 'Atorvastatin' }] },
    careTeam: { status: 'loaded', data: [{ id: 't1', title: 'Primary Care Team' }] },
    encounters: { status: 'loaded', data: [{ id: 'e1', title: 'Office Visit', detail: 'Follow-up', startDate: '2026-05-05', dateSort: 1 }] },
    sections: [
      {
        id: 'clinical',
        cards: [
          { id: 'allergies', title: 'Allergies', state: { status: 'loaded', data: [{ id: 'a1', title: 'Penicillin' }] } },
          { id: 'conditions', title: 'Problem List', state: { status: 'loaded', data: [{ id: 'c1', title: 'Hypertension' }] } },
          { id: 'medications', title: 'Medications', state: { status: 'loaded', data: [{ id: 'm1', title: 'Metformin' }] } },
          { id: 'prescriptions', title: 'Prescriptions', state: { status: 'loaded', data: [{ id: 'r1', title: 'Atorvastatin' }] } },
        ],
      },
      {
        id: 'dashboard',
        cards: [
          { id: 'care-team', title: 'Care Team', state: { status: 'loaded', data: [{ id: 't1', title: 'Primary Care Team' }] } },
          { id: 'encounters', title: 'Encounter History', state: { status: 'loaded', data: [{ id: 'e1', title: 'Office Visit', detail: 'Follow-up', startDate: '2026-05-05', dateSort: 1 }] } },
          { id: 'demographics', title: 'Demographics', state: { status: 'loaded', data: [{ id: 'd1', title: 'Phone', detail: '(217) 555-0198' }] } },
          { id: 'appointments', title: 'Appointments', state: { status: 'loaded', data: [] } },
        ],
      },
    ],
  };
}
