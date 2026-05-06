# Week 2 Demo Checklist

## Story

Show that AgentForge keeps OpenEMR as the clinical trust boundary while adding document extraction, guideline retrieval, LangGraph worker routing, and source-grounded answers.

## Recording Flow

1. Open a synthetic patient chart in OpenEMR.
2. Open OpenEMR Documents and show a lab PDF or intake form stored on the patient.
3. Click `Extract` in the document viewer.
4. Show the extracted structured facts table and raw JSON.
5. Return to Clinical Co-Pilot.
6. Ask a lab, medication, or allergy question.
7. Show grouped sources: Patient Chart, Extracted Documents, Guidelines.
8. Open a document fact source back to the OpenEMR document viewer.
9. Expand the trace panel and show the LangGraph route and worker handoffs.
10. Run the Week 2 eval command and show 50/50 passing.
11. Open Langfuse and show PHI-safe graph spans if credentials are configured.

## Commands

```shell
PYTHONPATH=agentforge/sidecar agentforge/sidecar/.venv/bin/python -m unittest discover -s agentforge/sidecar/tests
PYTHONPATH=agentforge/sidecar agentforge/sidecar/.venv/bin/python agentforge/evals/run_week2_evals.py
```
