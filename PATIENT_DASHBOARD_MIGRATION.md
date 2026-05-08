# Patient Dashboard Migration Defense

## Summary

The surprise challenge asks for the OpenEMR patient dashboard presentation layer to be reimplemented in a modern framework without changing the backend. AgentForge implements this as an embedded React + TypeScript + Vite section inside the existing OpenEMR patient dashboard.

The original dashboard route, patient context, and OpenEMR login flow remain intact. The modernized section is mounted by:

```text
/interface/patient_file/summary/demographics.php
```

It replaces the existing Dashboard page content area while preserving the same Dashboard tab, page route, patient context, and OpenEMR application login.

## Framework Choice

React was chosen because the dashboard is card-driven, stateful, and benefits from small reusable components for loading, empty, error, and populated states. TypeScript was chosen because clinical resources are flexible and nested; normalizing them into typed view models makes the data mapping easier to test and review. Vite was chosen because it produces static assets that OpenEMR can serve from the existing webroot, avoiding a new production frontend server.

This combination gives the project a modern presentation layer while preserving OpenEMR as the system of record and authorization boundary.

## Architecture

The submitted flow is same-origin and session-backed:

```text
OpenEMR login -> Existing patient dashboard PHP -> React/Vite section hydrated with dashboard data
```

The React bundle is compiled to:

```text
/interface/modules/custom_modules/agentforge/public/patient-dashboard/
```

Authentication is inherited from the OpenEMR application session. There is no second SMART/OIDC prompt for clinicians when they open the patient dashboard. The embedded section reuses existing OpenEMR services and dashboard queries, then passes a small JSON view model to React.

The standalone SMART/FHIR launcher remains useful for isolated frontend tests, but it is not the demo path for this challenge.

## Data Mapping

The dashboard maps existing OpenEMR patient dashboard data into compact UI view models:

| Dashboard area | Existing source |
| --- | --- |
| Patient header | `getPatientData()` |
| Allergies | `AllergyIntoleranceService` |
| Problem List | `PatientIssuesService` medical problems |
| Medications | `PatientIssuesService` medications |
| Prescriptions | `prescriptions` table |
| Care Team | `CareTeamService` |
| Encounter History | `form_encounter` with encounter categories |

Every card supports loading, empty, error, and populated states so missing demo data does not break the page.

## What We Gained

- Componentized dashboard cards instead of server-rendered card fragments.
- Typed normalizers and UI view models with unit tests.
- A static deploy artifact that lives inside the existing OpenEMR module.
- Clear separation between presentation code and OpenEMR backend logic.
- Easier UI iteration without changing PHP controllers or database queries.
- A demo that modernizes the actual dashboard page judges will inspect.

## Tradeoffs

- The embedded view is read-only and leaves edit actions in the existing OpenEMR cards.
- User-specific card collapse preferences are not replicated in the React version.
- The React section intentionally normalizes to a practical dashboard view rather than duplicating every PHP template detail.
- The standalone SMART/FHIR flow still needs client registration when used for frontend isolation tests.

## Demo Setup

1. Build and copy the Vite assets.
2. Log in to OpenEMR normally.
3. Select a patient.
4. Open the existing patient Dashboard tab.
5. Confirm the whole dashboard card area is rendered by the modern React view, with no extra Modern Dashboard subtab.

## Verification

Run the frontend checks:

```shell
cd agentforge/patient-dashboard
npm test
npm run build:openemr
```

Run the existing AgentForge gate:

```shell
.githooks/pre-push
```
