# AgentForge MVP Submission

## Submission Checklist

- GitHub repository: OpenEMR fork with AgentForge MVP documentation.
- Deployed application: https://openemr-production-5533.up.railway.app
- Audit document: [`AUDIT.md`](AUDIT.md)
- User document: [`USERS.md`](USERS.md) and compatibility pointer [`USER.md`](USER.md)
- Architecture document: [`ARCHITECTURE.md`](ARCHITECTURE.md)
- README setup and deployment notes: [`README.md`](README.md)

## MVP Status

This submission completes the MVP foundation stage. Per the AgentForge PDF, the MVP is not a working AI agent. The current work establishes the deployed OpenEMR surface, audit findings, target user, use cases, and architecture plan for the Clinical Co-Pilot.

The sidecar, OpenEMR module shell, mocked evidence-bundle response, eval runner, and observability wiring are planned for the next submission stage.

## Deployed App

Public URL: https://openemr-production-5533.up.railway.app

The Railway deployment is configured as an OpenEMR service backed by a MariaDB service. The deployment is demo-only and is not production hardened. It must not be used with real PHI.

## Demo Video Outline

1. Open the public Railway URL and show OpenEMR is reachable.
2. Explain that the MVP stage is foundation-only, not a working agent.
3. Summarize the audit's most important finding: OpenEMR must remain the clinical trust boundary.
4. Walk through the target user: hospitalist preparing for rounds.
5. Explain the planned workflows: chart brief, follow-up questions, missing-data warnings, and refusal of treatment directives.
6. Explain the architecture: OpenEMR module builds a bounded evidence bundle; sidecar transforms and verifies; every claim must cite source evidence.
7. Close with next steps for Early Submission: implement module shell, sidecar mock, verification contract, eval smoke tests, and trace logging.

## Known Limitations

- No working AI agent is implemented in this MVP.
- No sidecar is deployed.
- No real PHI may be used.
- The deployment is not production HIPAA-ready.
- The current OpenEMR deployment is intended for accessibility and demonstration, not clinical use.

## Next-Step Roadmap

- Add `interface/modules/custom_modules/agentforge/` with a patient-context panel and module-local endpoint.
- Add `agentforge/sidecar/` with a FastAPI mock that accepts a signed evidence bundle and returns verified, partial, refused, or failed responses.
- Add `agentforge/contracts/` with request and response schemas.
- Add eval smoke tests for missing data, unsupported citation, prompt injection, unauthorized patient, collector failure, and treatment-directive refusal.
- Add PHI-safe trace logging with request IDs, collector statuses, token/cost placeholders, and verification status.
