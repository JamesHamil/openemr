# AgentForge Project Checkpoint Demo Video Script

Target length: 3-5 minutes  
Submission items: repository URL and demo video  
Purpose: communicate the committed Clinical Co-Pilot direction, the technical decisions behind it, the trade-offs made, and the hardest problems encountered during this checkpoint.

## Recording Setup

- Show the submitted repository URL first: https://labs.gauntletai.com/jameshamil/openemr
- Open the deployed app: https://openemr-production-5533.up.railway.app
- Keep these files ready:
  - `AUDIT.md`
  - `USERS.md`
  - `ARCHITECTURE.md`
  - `MVP_SUBMISSION.md`
- Do not enter real patient data or real PHI. This checkpoint is demo-data-only.

## Script

### 0:00-0:30 - What I Built And Where It Is

Show the GitLab repository URL, then the Railway URL.

Say:

"This is my AgentForge Clinical Co-Pilot project checkpoint. I am submitting the repository URL and this demo video. The deployed OpenEMR fork is live on Railway at this URL."

"The goal here is not to claim a finished AI agent. This checkpoint shows the project direction I am committing to: deploy OpenEMR, audit the system, define a real user, and defend a codebase-informed architecture for a trustworthy clinical agent."

"The live app redirects into OpenEMR's login flow. This is demo-only, with no real PHI and no production HIPAA claim."

### 0:30-1:05 - The User And Product Direction

Show `USERS.md`.

Say:

"My target user is a hospitalist preparing for inpatient rounds. I chose that user because the workflow has a clear, high-pressure information problem: before entering the room, the physician needs to know what changed, what matters today, and what evidence supports the summary."

"A key trade-off was choosing the hospitalist instead of a nurse. A nurse workflow is valid, but it pushes the product toward bedside task orchestration: med timing, vitals monitoring, care tasks, and flowsheets. I narrowed the project to hospitalists first because the core capability should be chart synthesis with evidence, not real-time task assignment."

"The core use cases are a pre-round patient brief, patient-scoped follow-up questions, missing-data warnings, and refusal of treatment directives unless they are reframed as issues for physician review."

### 1:05-1:55 - Key Architecture Decision: OpenEMR Stays The Trust Boundary

Show `AUDIT.md`, then the architecture diagram in `ARCHITECTURE.md`.

Say:

"The most important decision is that OpenEMR remains the clinical trust boundary. The AI sidecar should not have database credentials, independent chart access, or authority to decide whether a user can see a patient."

"That came directly from the audit. The biggest security risk is over-disclosing PHI. The biggest reliability risk is a fluent but unsupported clinical claim. In healthcare, an answer has to trace back to the patient's actual record."

"The planned flow is: OpenEMR validates session state, CSRF, patient context, encounter context, and authorization. Then it builds a bounded evidence bundle. The sidecar only receives that bundle and cannot fetch more chart data on its own."

"The trade-off is less flexibility than direct database or FHIR access. But it is safer, easier to audit, and keeps authorization inside the system that already owns it."

### 1:55-2:45 - Key Architecture Decision: Hybrid Sidecar, Not Multi-Agent

Show the sidecar section or diagram in `ARCHITECTURE.md`.

Say:

"The second major decision is a hybrid sidecar architecture. OpenEMR owns clinical data access and user context. The sidecar owns AI orchestration, model calls, response formatting, and verification."

"I rejected a pure OpenEMR-only implementation because prompts, provider config, evals, and observability would be harder to isolate inside the PHP app. I also rejected multi-agent architecture because it adds complexity without a user-driven reason."

"OpenAI is the planned LLM provider because structured outputs help with schema-first verification. But the provider stays abstracted behind the sidecar."

"Conversation state is scoped to `conversation_id`, `patient_id`, `encounter_id`, and the evidence bundle. Switching patients resets clinical context."

### 2:45-3:35 - Verification, Failure Modes, And Speed Trade-Offs

Show the verification/status section in `ARCHITECTURE.md`.

Say:

"The core safety mechanism is verification. Every factual claim should be checked against the evidence bundle before it reaches the physician. The output statuses are `verified`, `partial`, `refused`, and `failed`."

"If the model says the patient is on a medication, the verifier needs a medication source. If it says a lab changed, it needs the lab record and timestamp. Unsupported claims are removed, downgraded, or returned as partial."

"The biggest product trade-off is speed versus completeness. A hospitalist needs something useful in seconds, but a full chart review can take longer. My approach is accuracy-first: return the first useful verified response, and if a collector times out, return a partial answer with a warning."

"For treatment requests, the agent refuses directives. It can summarize record-backed concerns, but the physician remains the decision-maker."

### 3:35-4:25 - Hardest Problems And How I Solved Them

Show `MVP_SUBMISSION.md`, then briefly show `Dockerfile.railway` if useful.

Say:

"The hardest implementation problem was deployment honesty. Railway could run the official `openemr/openemr:latest` image, but that would not show my fork being deployed. I solved that with `Dockerfile.railway`, which uses the official image as the base but builds from this repository."

"That preserved the known OpenEMR runtime while making the deployment traceable to this fork. Railway confirmed `builder: DOCKERFILE` and `dockerfilePath: Dockerfile.railway`."

"The second issue was runtime config. After deploy, OpenEMR briefly redirected to setup because the fresh container had a default `sqlconf.php`. I repaired it so it points back to Railway MariaDB. Next I would automate that with a persistent `sites` volume or startup wrapper."

"The hardest design problem was preventing the AI layer from becoming a second EHR with loose access to everything. The evidence bundle solves that by forcing OpenEMR to authorize and scope data first."

### 4:25-5:00 - Close: What Is Delivered And What Comes Next

Show `MVP_SUBMISSION.md`.

Say:

"For this checkpoint, I delivered a public OpenEMR deployment, an audit, a user document, an architecture defense, and a next-step roadmap."

"The next implementation phase is an OpenEMR module shell, mocked sidecar endpoint, evidence-bundle schemas, verifier statuses, eval smoke tests, and PHI-safe observability."

"The main design principle is that unsupported confidence is dangerous in a clinical setting. This architecture is built around bounded data access, source-backed answers, visible uncertainty, and physician control."
