import { LoadState, PatientHeader as PatientHeaderView } from '../fhir/types';

export function PatientHeader({ state }: { state: LoadState<PatientHeaderView> }) {
  if (state.status === 'loading') {
    return (
      <header className="af-patient-header">
        <div>
          <p className="af-dashboard-eyebrow">Patient Dashboard</p>
          <h1>Loading patient</h1>
        </div>
      </header>
    );
  }
  if (state.status === 'error') {
    return (
      <header className="af-patient-header af-patient-header--error">
        <div>
          <p className="af-dashboard-eyebrow">Patient Dashboard</p>
          <h1>Patient unavailable</h1>
          <p>{state.message}</p>
        </div>
      </header>
    );
  }
  const patient = state.data;
  return (
    <header className="af-patient-header">
      <div>
        <p className="af-dashboard-eyebrow">Patient Dashboard</p>
        <h1>{patient.name}</h1>
      </div>
      <dl className="af-patient-header__facts">
        <div>
          <dt>DOB</dt>
          <dd>{patient.dateOfBirth}</dd>
        </div>
        <div>
          <dt>Sex</dt>
          <dd>{patient.sex}</dd>
        </div>
        <div>
          <dt>MRN</dt>
          <dd>{patient.mrn}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>{patient.active ? 'Active' : 'Inactive'}</dd>
        </div>
      </dl>
    </header>
  );
}
