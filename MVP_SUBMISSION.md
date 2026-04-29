# AgentForge Submission Checkpoint

## Submission Checklist

- Repository: OpenEMR fork with AgentForge project documentation.
- Deployed application: https://openemr-production-5533.up.railway.app
- Audit document: [`AUDIT.md`](AUDIT.md)
- User document: [`USERS.md`](USERS.md)
- Architecture document: [`ARCHITECTURE.md`](ARCHITECTURE.md)
- README setup and deployment notes: [`README.md`](README.md)
- Demo video script: [`VIDEO_SCRIPT.md`](VIDEO_SCRIPT.md)

## Checkpoint Status

This submission checkpoint demonstrates the foundation for the committed Clinical Co-Pilot direction. The current work establishes the deployed OpenEMR surface, audit findings, target user, use cases, and architecture plan that will guide the full project.

The current deployment is not yet a working AI agent. The sidecar, OpenEMR module shell, mocked evidence-bundle response, eval runner, and observability wiring are the next implementation phase of the same architecture.

## Deployed App

Public URL: https://openemr-production-5533.up.railway.app

The Railway deployment is configured as an OpenEMR service backed by a MariaDB service. The deployment is demo-only and is not production hardened. It must not be used with real PHI.

## Demo Video Outline

1. Show the repository URL and public Railway URL.
2. Explain that this checkpoint is foundation-only, not a working agent yet.
3. Defend the user choice: hospitalist preparing for rounds.
4. Explain the key decision that OpenEMR remains the clinical trust boundary.
5. Explain the hybrid sidecar architecture and why it is not multi-agent.
6. Discuss verification, failure modes, and the speed-versus-completeness trade-off.
7. Describe the hardest deployment and design problems encountered and how they were solved.
8. Close with the next implementation phase: module shell, sidecar mock, verification contract, eval smoke tests, and PHI-safe observability.

The full 3-5 minute narration script is in [`VIDEO_SCRIPT.md`](VIDEO_SCRIPT.md). It is structured around key decisions, trade-offs, hardest problems, and clear technical explanation of the architecture.

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
