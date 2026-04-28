## Slide 1

Open by framing this as a clinical safety architecture, not just an AI feature.
  The core idea is a hospitalist rounding assistant that helps prepare a patient-specific brief and answer follow-up questions, but only when every clinical claim is traceable back to OpenEMR evidence.
  The defense is about why we draw the trust boundary where we do, why the LLM is boxed in, and how failures become visible instead of hidden.

## Slide 2

This slide sets up the stakes.
  We are not building a general chatbot where the model can improvise from a giant chart dump.
  Hospitalists need quick orientation, but the output has to be auditable because even small unsupported claims can change a clinical decision.
  That is why the architecture is accuracy-first: partial verified answers with warnings are acceptable; fast unverifiable answers are not.

## Slide 3

The scope is deliberately tight.
  We picked one user and one workflow: a hospitalist getting ready for rounds.
  The system can summarize, answer follow-ups, and refuse or reframe unsafe treatment requests.
  It cannot write orders, invent a plan, or jump to another patient based on conversation.
  That narrowness is a feature: it gives us a stable safety case and a realistic MVP.

## Slide 4

This is the main architectural defense.
  We could have put everything in PHP, but that makes LLM orchestration and provider evolution awkward.
  We could have built a standalone agent, but that moves too much clinical authority outside OpenEMR.
  The hybrid design keeps OpenEMR responsible for identity, authorization, evidence collection, and patient-linked audit.
  The sidecar is powerful enough to structure and verify the response, but it is intentionally unable to browse the chart on its own.

## Slide 5

Walk the room through the request path.
  The browser never talks directly to the sidecar or the model.
  OpenEMR validates the user and patient, applies rate limiting, and assembles the evidence bundle.
  The sidecar then has one job: turn that bounded bundle into structured output and verify it.
  The important performance nuance is first useful response, not total chart exhaustion.
  If collection times out or an adapter is missing, the answer can still be partial, but the warning is explicit.

## Slide 6

This slide explains why the sidecar is more than a prompt wrapper.
  The model can generate a useful clinical narrative, but the verifier decides what is allowed to appear as a clinical claim.
  A citation label alone is too weak, because the model can cite the wrong thing.
  Our claim must map to a record type, field path or text span, value, and timestamp in the evidence bundle.
  If that proof is missing, the system either marks the answer partial, refuses, or fails visibly.

## Slide 7

This is where the practical engineering controls come together.
  Patient context resets on switch, because conversation memory cannot follow a clinician into a different chart.
  Secrets stay on the server side, and the browser never receives sidecar or LLM credentials.
  OpenEMR keeps the clinical audit trail, while the sidecar keeps only PHI-safe technical traces.
  The test plan mirrors the risk model: unsupported citation, missing data, prompt injection, unauthorized patient, and collector failure all need smoke evals.

## Slide 8

Close by restating the defense in one sentence: this is a constrained evidence system, not an autonomous clinician.
  The hybrid split is the key: OpenEMR remains the trusted clinical boundary, while the sidecar handles the parts that change quickly in the AI stack.
  OpenAI is the v1 provider because structured outputs help us enforce schemas, but the provider is abstracted and we are not claiming the model is medically safe on its own.
  The safety comes from bounded evidence, verification, explicit warnings, and human decision-making.
  End with the product promise: say less, cite precisely, warn clearly, or refuse.
