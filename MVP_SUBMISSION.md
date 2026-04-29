# AgentForge Submission Checkpoint

## Submission Checklist

- Repository: OpenEMR fork with AgentForge project documentation.
- Deployed application: https://openemr-production-5533.up.railway.app
- Audit document: [`AUDIT.md`](AUDIT.md)
- User document: [`USERS.md`](USERS.md)
- Architecture document: [`ARCHITECTURE.md`](ARCHITECTURE.md)
- README setup and deployment notes: [`README.md`](README.md)

## Checkpoint Status

This submission checkpoint demonstrates the foundation for the committed Clinical Co-Pilot direction. The current work establishes the deployed OpenEMR surface, audit findings, target user, use cases, and architecture plan that will guide the full project.

The current deployment is not yet a working AI agent. The sidecar, OpenEMR module shell, mocked evidence-bundle response, eval runner, and observability wiring are the next implementation phase of the same architecture.

## Deployed App

Public URL: https://openemr-production-5533.up.railway.app

The Railway deployment is configured as an OpenEMR service backed by a MariaDB service. The deployment is demo-only and is not production hardened. It must not be used with real PHI.

## Current Delivery Limits

- No working AI agent is implemented in this checkpoint.
- No sidecar is deployed.
- No real PHI may be used.
- The deployment is not production HIPAA-ready.
- The current OpenEMR deployment is intended for accessibility and demonstration, not clinical use.

## Implementation Roadmap

- Add `interface/modules/custom_modules/agentforge/` with a patient-context panel and module-local endpoint.
- Add `agentforge/sidecar/` with a FastAPI mock that accepts a signed evidence bundle and returns verified, partial, refused, or failed responses.
- Add `agentforge/contracts/` with request and response schemas.
- Add eval smoke tests for missing data, unsupported citation, prompt injection, unauthorized patient, collector failure, and treatment-directive refusal.
- Add PHI-safe trace logging with request IDs, collector statuses, token/cost placeholders, and verification status.
