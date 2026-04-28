# AgentForge Target User And Use Cases

## Target User

The first user is a hospitalist preparing for inpatient rounds. This physician is responsible for quickly understanding several admitted patients before entering rooms, speaking with patients and families, coordinating with nurses, and making clinical decisions under time pressure.

This user is intentionally narrower than "doctor" or "clinician." A hospitalist's work is chart-heavy, time-sensitive, and patient-specific. They need to know what changed since the last review, which data is relevant now, and where each fact came from in the record. They do not need a general medical chatbot, and they should not delegate clinical judgment to an AI system.

## Workflow Moment

The agent enters the day during pre-rounding or between patient rooms. The hospitalist has a selected patient open in OpenEMR and needs a concise, source-backed view of the chart before speaking with the patient. They may ask follow-up questions about changes, medication list items, labs, vitals, allergies, notes, or missing data.

The output is used to orient the physician, not to make autonomous decisions. The physician remains responsible for reviewing sources, deciding what matters, and taking any clinical action through normal OpenEMR workflows.

## Use Case 1: Pre-Round Chart Brief

**User problem:** The hospitalist needs a fast summary of what matters for one selected patient before entering the room.

**Agent behavior:** Generate a read-only chart brief from bounded OpenEMR evidence: active problems, allergies, current medications, recent labs, vitals, recent notes, and visible gaps.

**Why an agent:** The user may need different emphasis depending on the patient and moment. A conversational agent can produce a concise brief and then support follow-up questions without forcing the physician through several chart screens.

## Use Case 2: What Changed Since Last Review?

**User problem:** The hospitalist needs to know what changed overnight or since the prior encounter review.

**Agent behavior:** Surface source-backed changes in notes, labs, vitals, medication list items, and problem list evidence included in the retrieved bundle.

**Why an agent:** "What changed?" is contextual and usually spans multiple record types. A static dashboard can show raw values, but an agent can explain the cross-record change while citing each source and warning about missing collectors.

## Use Case 3: Patient-Scoped Follow-Up Questions

**User problem:** After reading a brief, the hospitalist asks targeted questions such as "What labs are abnormal?", "What meds are listed?", or "Do the notes mention shortness of breath?"

**Agent behavior:** Answer only inside the selected patient and encounter context, using the same evidence bundle or a newly authorized bundle if context changes.

**Why an agent:** Multi-turn context is useful because the physician is refining a line of thought during rounds. The system should remember the current patient context while refusing to carry clinical context across patient switches.

## Use Case 4: Missing Or Conflicting Data

**User problem:** The hospitalist needs to know whether the chart evidence is complete enough to trust the summary.

**Agent behavior:** Explicitly warn when data was not retrieved, is stale, is missing from retrieved records, or conflicts across sources.

**Why an agent:** The useful output is not only the answer; it is also uncertainty. A conversational interface can state limitations in clinical language and invite a more specific follow-up.

## Use Case 5: Unsafe Treatment Requests

**User problem:** A physician may ask the assistant a question that sounds like a treatment directive, such as whether to start, stop, or continue a medication.

**Agent behavior:** Refuse to provide treatment directives and reframe the response as record-backed issues for physician review.

**Why an agent:** The conversational surface makes refusal and reframing important. The agent can be helpful without pretending to be the decision-maker.

## Out Of Scope For MVP

- Writing notes, orders, prescriptions, diagnoses, billing records, or tasks.
- Broad multi-patient search.
- Nurse-specific action plans.
- Real PHI.
- Production HIPAA deployment.
- A working AI sidecar in the MVP stage.
