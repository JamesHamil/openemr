# AgentForge Submission Checkpoint

## Submission Checklist

- Repository: OpenEMR fork with AgentForge project documentation.
- Deployed application: https://openemr-production-5533.up.railway.app
- Audit document: [`AUDIT.md`](AUDIT.md)
- User document: [`USERS.md`](USERS.md)
- Architecture document: [`ARCHITECTURE.md`](ARCHITECTURE.md)
- README setup and deployment notes: [`README.md`](README.md)

## Checkpoint Status

This submission checkpoint demonstrates the foundation for the committed Clinical Co-Pilot direction. The current work establishes the deployed OpenEMR surface, audit findings, target user, use cases, architecture plan, and first execution artifacts that guide the full project.

The repository now includes the OpenEMR module shell, shared contracts, FastAPI sidecar, mock/real/off runtime modes, verifier, eval runner, and cost analysis. The Railway environment runs the sidecar in mock mode for deterministic demos; real OpenAI mode remains disabled unless server-side secrets and review-ready configuration are supplied.

## Deployed App

Public URL: https://openemr-production-5533.up.railway.app

The Railway deployment is configured as separate OpenEMR, MariaDB, and AgentForge sidecar services. OpenEMR is built from this fork with `Dockerfile.railway`, and the sidecar is private-network only. The deployment is demo-only and is not production hardened. It must not be used with real PHI.

## Current Delivery Limits

- No real PHI may be used.
- The deployment is not production HIPAA-ready.
- The current OpenEMR deployment is intended for accessibility and demonstration, not clinical use.
- Real OpenAI mode requires server-side `OPENAI_API_KEY` and review-ready sidecar configuration.
- The first OpenEMR evidence collectors are narrow and read-only; full inpatient MAR/order/task coverage is not implemented.

## Implemented Execution Slice

- `interface/modules/custom_modules/agentforge/`: patient-context panel, module-local endpoint, CSRF/ACL checks, rate limiting, read-only evidence bundle, sidecar signing, and audit event.
- `agentforge/sidecar/`: FastAPI sidecar with `/healthz`, `/v1/chat`, mock/real/off modes, verifier, and PHI-safe trace record.
- `agentforge/contracts/`: request and response JSON schemas.
- `agentforge/evals/`: smoke eval dataset and runner.
- `agentforge/COST_ANALYSIS.md`: AI cost and scale analysis.
