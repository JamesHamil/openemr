import {
  Presentation,
  PresentationFile,
  row,
  column,
  grid,
  panel,
  text,
  rule,
  fill,
  hug,
  fixed,
  wrap,
  fr,
  auto,
} from "@oai/artifact-tool";
import fs from "node:fs/promises";

const W = 1920;
const H = 1080;

const C = {
  paper: "#F6FAF7",
  ink: "#16231E",
  muted: "#5D6D68",
  line: "#C9D7D0",
  green: "#0D3B2E",
  green2: "#155F4A",
  teal: "#167C80",
  tealSoft: "#DCEFED",
  amber: "#C7922B",
  amberSoft: "#F4E8CC",
  red: "#B8453C",
  redSoft: "#F3D9D6",
  white: "#FFFFFF",
  slate: "#E8EFEB",
};

const presentation = Presentation.create({
  slideSize: { width: W, height: H },
});

function txt(value, options = {}) {
  return text(value, {
    width: options.width ?? fill,
    height: options.height ?? hug,
    name: options.name,
    style: {
      fontFace: "Aptos",
      fontSize: options.size ?? 28,
      color: options.color ?? C.ink,
      bold: options.bold ?? false,
      italic: options.italic ?? false,
      lineSpacingMultiple: options.lineSpacingMultiple ?? 1.05,
      ...options.style,
    },
  });
}

function root(children, opts = {}) {
  return panel(
    {
      name: "slide-root",
      width: fill,
      height: fill,
      fill: opts.fill ?? C.paper,
      padding: opts.padding ?? { x: 86, y: 64 },
    },
    children,
  );
}

function slideNo(n) {
  return txt(String(n).padStart(2, "0"), {
    name: "slide-number",
    width: fixed(64),
    size: 20,
    color: "#7E8F89",
    bold: true,
  });
}

function titleBlock(kicker, title, subtitle, opts = {}) {
  return column(
    { name: "title-stack", width: fill, height: hug, gap: 16 },
    [
      txt(kicker, {
        name: "kicker",
        size: 20,
        bold: true,
        color: opts.kickerColor ?? C.teal,
        style: { allCaps: true },
      }),
      txt(title, {
        name: "slide-title",
        size: opts.titleSize ?? 56,
        bold: true,
        color: opts.titleColor ?? C.ink,
        width: opts.titleWidth ?? wrap(1450),
        lineSpacingMultiple: 0.96,
      }),
      subtitle
        ? txt(subtitle, {
            name: "slide-subtitle",
            size: opts.subtitleSize ?? 28,
            color: opts.subtitleColor ?? C.muted,
            width: opts.subtitleWidth ?? wrap(1320),
          })
        : null,
    ].filter(Boolean),
  );
}

function chip(label, color = C.green, fillColor = C.white) {
  return panel(
    {
      name: `chip-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
      width: hug,
      height: hug,
      fill: fillColor,
      line: { color, weight: 2 },
      borderRadius: 22,
      padding: { x: 22, y: 10 },
    },
    txt(label, {
      size: 19,
      bold: true,
      color,
      width: hug,
      style: { lineSpacingMultiple: 1 },
    }),
  );
}

function claim(label, detail, color = C.green, fillColor = C.white) {
  return panel(
    {
      name: `claim-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
      width: fill,
      height: fill,
      fill: fillColor,
      line: { color: C.line, weight: 1 },
      borderRadius: 10,
      padding: { x: 26, y: 24 },
    },
    column({ width: fill, height: fill, gap: 12 }, [
      txt(label, { size: 29, bold: true, color }),
      txt(detail, { size: 21, color: C.muted, lineSpacingMultiple: 1.12 }),
    ]),
  );
}

function node(label, detail, opts = {}) {
  return panel(
    {
      name: `node-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
      width: opts.width ?? fill,
      height: opts.height ?? fixed(132),
      fill: opts.fill ?? C.white,
      line: { color: opts.line ?? C.line, weight: opts.weight ?? 1.5 },
      borderRadius: 9,
      padding: { x: 22, y: 18 },
    },
    column({ width: fill, height: fill, gap: 8 }, [
      txt(label, { size: opts.labelSize ?? 25, bold: true, color: opts.color ?? C.ink }),
      detail
        ? txt(detail, {
            size: opts.detailSize ?? 18,
            color: opts.detailColor ?? C.muted,
            lineSpacingMultiple: 1.1,
          })
        : null,
    ].filter(Boolean)),
  );
}

function arrow(label = "->") {
  return txt(label, {
    name: "flow-arrow",
    width: fixed(58),
    size: 30,
    bold: true,
    color: C.teal,
    style: { textAlign: "center" },
  });
}

function addSlide(content, notes) {
  const slide = presentation.slides.add();
  slide.compose(content, {
    frame: { left: 0, top: 0, width: W, height: H },
    baseUnit: 8,
  });
  slide.speakerNotes.setText(notes.trim());
  return slide;
}

addSlide(
  root(
    column({ width: fill, height: fill, gap: 42, justify: "between" }, [
      row({ width: fill, height: hug, justify: "between", align: "center" }, [
        chip("AgentForge + OpenEMR", C.green, "#ECF5F0"),
        txt("Architecture Defense", { width: hug, size: 22, color: C.muted, bold: true }),
      ]),
      column({ width: fill, height: fill, gap: 28, justify: "center" }, [
        txt("Clinical Co-Pilot", {
          name: "deck-title",
          size: 86,
          bold: true,
          color: C.green,
          width: wrap(1120),
          lineSpacingMultiple: 0.92,
        }),
        txt("A source-backed hospitalist rounding assistant inside OpenEMR", {
          name: "deck-subtitle",
          size: 36,
          color: C.ink,
          width: wrap(980),
        }),
        rule({ name: "title-rule", width: fixed(260), stroke: C.amber, weight: 6 }),
      ]),
      row({ width: fill, height: hug, justify: "between", align: "end" }, [
        txt("Five-minute technical defense", { width: hug, size: 22, color: C.muted }),
        slideNo(1),
      ]),
    ]),
  ),
  `
  Open by framing this as a clinical safety architecture, not just an AI feature.
  The core idea is a hospitalist rounding assistant that helps prepare a patient-specific brief and answer follow-up questions, but only when every clinical claim is traceable back to OpenEMR evidence.
  The defense is about why we draw the trust boundary where we do, why the LLM is boxed in, and how failures become visible instead of hidden.
  `,
);

addSlide(
  root(
    column({ width: fill, height: fill, gap: 46 }, [
      titleBlock(
        "Problem",
        "The hard part is not generating text. It is earning trust under time pressure.",
        "Before rounds, clinicians need the right chart changes quickly. A fluent unsupported answer is worse than no answer.",
      ),
      grid(
        {
          name: "problem-grid",
          width: fill,
          height: fill,
          columns: [fr(1), fr(1), fr(1)],
          gap: 22,
        },
        [
          claim("Time pressure", "Rounds create a narrow window to absorb overnight notes, active meds, vitals, labs, and missing data.", C.teal, "#F8FEFD"),
          claim("Chart fragmentation", "Relevant evidence lives across encounters, orders, notes, labs, and medication lists.", C.green, "#FBFDFC"),
          claim("Clinical risk", "If the system cannot cite the record, warn about gaps, or refuse unsafe requests, it should not answer.", C.red, "#FFF9F8"),
        ],
      ),
      row({ width: fill, height: hug, justify: "between", align: "center" }, [
        txt("Design target: help the physician decide faster without becoming the decision-maker.", {
          width: wrap(1300),
          size: 25,
          bold: true,
          color: C.green,
        }),
        slideNo(2),
      ]),
    ]),
  ),
  `
  This slide sets up the stakes.
  We are not building a general chatbot where the model can improvise from a giant chart dump.
  Hospitalists need quick orientation, but the output has to be auditable because even small unsupported claims can change a clinical decision.
  That is why the architecture is accuracy-first: partial verified answers with warnings are acceptable; fast unverifiable answers are not.
  `,
);

addSlide(
  root(
    column({ width: fill, height: fill, gap: 42 }, [
      titleBlock(
        "V1 Scope",
        "Narrow user, narrow moment, narrow authority.",
        "The first version serves a hospitalist preparing for rounds on a selected patient.",
        { titleSize: 48, subtitleSize: 25 },
      ),
      grid(
        {
          name: "scope-grid",
          width: fill,
          height: fill,
          columns: [fr(1), fr(1), fr(1)],
          rows: [fr(1), auto],
          columnGap: 22,
          rowGap: 28,
        },
        [
          node("1. Pre-round brief", "Retrieved chart summary for the selected patient, grounded in OpenEMR-collected evidence.", {
            height: fill,
            color: C.green,
            fill: C.white,
          }),
          node("2. Follow-up Q&A", "Patient-scoped questions about changes, meds, labs, notes, contradictions, or missing data.", {
            height: fill,
            color: C.teal,
            fill: C.white,
          }),
          node("3. Safe refusal", "Treatment requests are reframed as record-backed issues for physician review, not directives.", {
            height: fill,
            color: C.red,
            fill: C.white,
          }),
          panel(
            {
              name: "scope-boundary",
              columnSpan: 3,
              width: fill,
              height: hug,
              fill: "#EDF5F1",
              line: { color: "#B8CEC4", weight: 1 },
              borderRadius: 9,
              padding: { x: 28, y: 20 },
            },
            row({ width: fill, height: hug, gap: 18, align: "center" }, [
              txt("Explicitly out of scope:", { width: hug, size: 23, bold: true, color: C.green }),
              txt("orders, diagnosis, treatment directives, hidden patient switching, and model-side chart retrieval.", {
                size: 23,
                color: C.ink,
              }),
            ]),
          ),
        ],
      ),
      row({ width: fill, height: hug, justify: "end" }, [slideNo(3)]),
    ]),
  ),
  `
  The scope is deliberately tight.
  We picked one user and one workflow: a hospitalist getting ready for rounds.
  The system can summarize, answer follow-ups, and refuse or reframe unsafe treatment requests.
  It cannot write orders, invent a plan, or jump to another patient based on conversation.
  That narrowness is a feature: it gives us a stable safety case and a realistic MVP.
  `,
);

addSlide(
  root(
    column({ width: fill, height: fill, gap: 34 }, [
      titleBlock(
        "Architecture Choice",
        "OpenEMR stays the trusted clinical boundary. The sidecar stays a constrained evidence transformer.",
        "This is a hybrid architecture: PHP/OpenEMR owns authorization and collection; FastAPI owns orchestration, LLM calls, and verification.",
        { titleSize: 48 },
      ),
      grid(
        {
          name: "boundary-grid",
          width: fill,
          height: fill,
          columns: [fr(1), fr(0.9)],
          gap: 30,
        },
        [
          panel(
            {
              name: "openemr-boundary",
              width: fill,
              height: fill,
              fill: "#EAF4EE",
              line: { color: "#9BB9AC", weight: 2 },
              borderRadius: 12,
              padding: { x: 30, y: 26 },
            },
            column({ width: fill, height: fill, gap: 20 }, [
              txt("OpenEMR module", { size: 34, bold: true, color: C.green }),
              txt("Authenticates user, enforces patient access, collects chart evidence, signs the bounded bundle, writes patient-linked audit.", {
                size: 24,
                color: C.ink,
              }),
              row({ width: fill, height: hug, gap: 14 }, [
                chip("authorization", C.green, C.white),
                chip("collection", C.green, C.white),
                chip("audit", C.green, C.white),
              ]),
            ]),
          ),
          panel(
            {
              name: "sidecar-boundary",
              width: fill,
              height: fill,
              fill: "#EEF8F8",
              line: { color: "#98CAC9", weight: 2 },
              borderRadius: 12,
              padding: { x: 30, y: 26 },
            },
            column({ width: fill, height: fill, gap: 20 }, [
              txt("FastAPI sidecar", { size: 34, bold: true, color: C.teal }),
              txt("Receives only the signed RoundingContextBundle, calls OpenAI through an abstract provider, verifies every output claim, and returns status.", {
                size: 24,
                color: C.ink,
              }),
              row({ width: fill, height: hug, gap: 14 }, [
                chip("orchestration", C.teal, C.white),
                chip("LLM", C.teal, C.white),
                chip("verification", C.teal, C.white),
              ]),
            ]),
          ),
        ],
      ),
      row({ width: fill, height: hug, justify: "between", align: "center" }, [
        txt("The sidecar has no DB credentials, no OpenEMR API token, and no callback tool to fetch more chart data.", {
          width: wrap(1350),
          size: 24,
          bold: true,
          color: C.red,
        }),
        slideNo(4),
      ]),
    ]),
  ),
  `
  This is the main architectural defense.
  We could have put everything in PHP, but that makes LLM orchestration and provider evolution awkward.
  We could have built a standalone agent, but that moves too much clinical authority outside OpenEMR.
  The hybrid design keeps OpenEMR responsible for identity, authorization, evidence collection, and patient-linked audit.
  The sidecar is powerful enough to structure and verify the response, but it is intentionally unable to browse the chart on its own.
  `,
);

addSlide(
  root(
    column({ width: fill, height: fill, gap: 32 }, [
      titleBlock(
        "Request Flow",
        "The model only sees a bounded evidence bundle, never the whole chart.",
        "The response is useful early, but verification is never skipped for speed.",
        { titleSize: 50 },
      ),
      row({ width: fill, height: fixed(252), gap: 16, align: "center" }, [
        node("Browser UI", "Hospitalist selects patient or asks a patient-scoped question.", { height: fixed(154), color: C.ink }),
        arrow(),
        node("OpenEMR module", "Checks session, patient access, encounter scope, and rate limits.", { height: fixed(154), color: C.green }),
        arrow(),
        node("Collectors", "Build bounded evidence from notes, meds, labs, vitals, orders, and gaps.", { height: fixed(154), color: C.green }),
        arrow(),
        node("Signed bundle", "conversation_id + patient_id + encounter_id + evidence_bundle.", { height: fixed(154), color: C.amber, fill: "#FFFDF8" }),
      ]),
      row({ width: fill, height: fixed(252), gap: 16, align: "center" }, [
        node("Sidecar", "Single orchestrator. No multi-agent autonomy, no raw chart persistence.", { height: fixed(154), color: C.teal }),
        arrow(),
        node("OpenAI provider", "Schema-first structured output; provider abstracted behind config.", { height: fixed(154), color: C.teal }),
        arrow(),
        node("Verifier", "Claims must map back to specific evidence fields or spans.", { height: fixed(154), color: C.red, fill: "#FFF9F8" }),
        arrow(),
        node("UI + audit", "Verified, partial, refused, or failed response with warnings and citations.", { height: fixed(154), color: C.green }),
      ]),
      row({ width: fill, height: hug, justify: "between", align: "center" }, [
        txt("Timeouts return partial verified answers with warnings; they do not silently lower the evidence standard.", {
          width: wrap(1350),
          size: 24,
          bold: true,
          color: C.green,
        }),
        slideNo(5),
      ]),
    ]),
  ),
  `
  Walk the room through the request path.
  The browser never talks directly to the sidecar or the model.
  OpenEMR validates the user and patient, applies rate limiting, and assembles the evidence bundle.
  The sidecar then has one job: turn that bounded bundle into structured output and verify it.
  The important performance nuance is first useful response, not total chart exhaustion.
  If collection times out or an adapter is missing, the answer can still be partial, but the warning is explicit.
  `,
);

addSlide(
  root(
    column({ width: fill, height: fill, gap: 34 }, [
      titleBlock(
        "Verification",
        "Citations are not enough. Every clinical claim needs a source-bound proof.",
        "The verifier is deliberately stricter than the language model.",
        { titleSize: 52 },
      ),
      grid(
        {
          name: "verification-grid",
          width: fill,
          height: fill,
          columns: [fr(1), fr(1.15)],
          gap: 34,
        },
        [
          panel(
            {
              name: "claim-example",
              width: fill,
              height: fill,
              fill: C.white,
              line: { color: C.line, weight: 1 },
              borderRadius: 10,
              padding: { x: 30, y: 28 },
            },
            column({ width: fill, height: fill, gap: 20 }, [
              txt("Model proposes:", { size: 24, bold: true, color: C.muted }),
              txt("Creatinine increased overnight and diuretics may need review.", {
                size: 38,
                bold: true,
                color: C.ink,
                lineSpacingMultiple: 1,
              }),
              rule({ width: fixed(200), stroke: C.amber, weight: 4 }),
              txt("Verifier asks: where exactly in the bundle is each factual claim supported?", {
                size: 24,
                color: C.green,
              }),
            ]),
          ),
          column({ width: fill, height: fill, gap: 18 }, [
            node("Evidence pointer", "record_type, record_id, field path or text span, value, timestamp.", {
              color: C.green,
              height: fixed(112),
            }),
            node("Status contract", "verified, partial, refused, or failed.", {
              color: C.teal,
              height: fixed(112),
            }),
            node("Contradiction surfacing", "Conflicting notes or stale values are shown as uncertainty, not resolved by the model.", {
              color: C.amber,
              fill: "#FFFDF8",
              height: fixed(112),
            }),
            node("Prompt injection defense", "Chart text is untrusted input; notes cannot override policy, scope, or verification rules.", {
              color: C.red,
              fill: "#FFF9F8",
              height: fixed(112),
            }),
          ]),
        ],
      ),
      row({ width: fill, height: hug, justify: "end" }, [slideNo(6)]),
    ]),
  ),
  `
  This slide explains why the sidecar is more than a prompt wrapper.
  The model can generate a useful clinical narrative, but the verifier decides what is allowed to appear as a clinical claim.
  A citation label alone is too weak, because the model can cite the wrong thing.
  Our claim must map to a record type, field path or text span, value, and timestamp in the evidence bundle.
  If that proof is missing, the system either marks the answer partial, refuses, or fails visibly.
  `,
);

addSlide(
  root(
    column({ width: fill, height: fill, gap: 36 }, [
      titleBlock(
        "Reliability",
        "The architecture is designed to fail visibly.",
        "In clinical software, an honest warning is safer than a confident guess.",
        { titleSize: 56 },
      ),
      grid(
        {
          name: "reliability-grid",
          width: fill,
          height: fill,
          columns: [fr(1), fr(1), fr(1)],
          rows: [fr(1), fr(1)],
          gap: 22,
        },
        [
          claim("Missing data", "The UI distinguishes missing, stale, and unavailable evidence instead of smoothing it over.", C.amber, "#FFFDF8"),
          claim("Collector failure", "Adapter gaps and timeouts become warnings attached to the answer.", C.red, "#FFF9F8"),
          claim("Patient switch", "Clinical context is scoped to conversation_id + patient_id + encounter_id + evidence_bundle.", C.green, "#FBFDFC"),
          claim("Secrets", "API keys remain server-side; browser never sees sidecar or LLM credentials.", C.teal, "#F8FEFD"),
          claim("Audit", "OpenEMR stores patient-linked actions; sidecar keeps PHI-safe technical traces only.", C.green, "#FBFDFC"),
          claim("Rollback", "Disable the module or route to mock/off mode without changing OpenEMR core.", C.red, "#FFF9F8"),
        ],
      ),
      row({ width: fill, height: hug, justify: "between", align: "center" }, [
        txt("Tests target schemas, verifier behavior, module-sidecar contracts, and smoke evals for dangerous failure modes.", {
          width: wrap(1320),
          size: 24,
          bold: true,
          color: C.green,
        }),
        slideNo(7),
      ]),
    ]),
  ),
  `
  This is where the practical engineering controls come together.
  Patient context resets on switch, because conversation memory cannot follow a clinician into a different chart.
  Secrets stay on the server side, and the browser never receives sidecar or LLM credentials.
  OpenEMR keeps the clinical audit trail, while the sidecar keeps only PHI-safe technical traces.
  The test plan mirrors the risk model: unsupported citation, missing data, prompt injection, unauthorized patient, and collector failure all need smoke evals.
  `,
);

addSlide(
  root(
    column({ width: fill, height: fill, gap: 36, justify: "between" }, [
      titleBlock(
        "Defense",
        "This is not a chatbot bolted onto a chart. It is a constrained clinical evidence system.",
        "The design is conservative because the domain deserves conservatism.",
        { titleSize: 54 },
      ),
      grid(
        {
          name: "closing-grid",
          width: fill,
          height: fill,
          columns: [fr(1), fr(1), fr(1)],
          gap: 22,
        },
        [
          claim("Why hybrid?", "OpenEMR owns trust and audit; the sidecar owns model orchestration and verification.", C.green, "#FBFDFC"),
          claim("Why OpenAI v1?", "Structured outputs support schema-first verification. We make no model-specific medical safety claim.", C.teal, "#F8FEFD"),
          claim("Why limited scope?", "A safe rounding assistant is more defensible than a broad autonomous agent.", C.amber, "#FFFDF8"),
        ],
      ),
      panel(
        {
          name: "closing-line",
          width: fill,
          height: hug,
          fill: C.green,
          borderRadius: 12,
          padding: { x: 34, y: 28 },
        },
        txt("The product promise: say less, cite precisely, warn clearly, or refuse.", {
          size: 38,
          bold: true,
          color: C.white,
          lineSpacingMultiple: 1,
        }),
      ),
      row({ width: fill, height: hug, justify: "between", align: "center" }, [
        txt("Next iteration: eval-driven improvement of collectors, prompts, schemas, audit logs, and physician feedback.", {
          width: wrap(1300),
          size: 22,
          color: C.muted,
        }),
        slideNo(8),
      ]),
    ]),
  ),
  `
  Close by restating the defense in one sentence: this is a constrained evidence system, not an autonomous clinician.
  The hybrid split is the key: OpenEMR remains the trusted clinical boundary, while the sidecar handles the parts that change quickly in the AI stack.
  OpenAI is the v1 provider because structured outputs help us enforce schemas, but the provider is abstracted and we are not claiming the model is medically safe on its own.
  The safety comes from bounded evidence, verification, explicit warnings, and human decision-making.
  End with the product promise: say less, cite precisely, warn clearly, or refuse.
  `,
);

await fs.mkdir("output", { recursive: true });
await fs.mkdir("scratch/previews", { recursive: true });

const pptxBlob = await PresentationFile.exportPptx(presentation);
await pptxBlob.save("output/output.pptx");

const notes = presentation.slides.items
  .map((slide, index) => `## Slide ${index + 1}\n\n${slide.speakerNotes.text.trim()}\n`)
  .join("\n");
await fs.writeFile("scratch/agentforge-architecture-defense-speaker-notes.md", notes, "utf8");

for (let i = 0; i < presentation.slides.items.length; i += 1) {
  const blob = await presentation.slides.items[i].export({ format: "png", width: 1280 });
  const bytes = Buffer.from(await blob.arrayBuffer());
  await fs.writeFile(`scratch/previews/slide-${String(i + 1).padStart(2, "0")}.png`, bytes);
}

console.log("Wrote output/output.pptx");
console.log("Wrote scratch/agentforge-architecture-defense-speaker-notes.md");
console.log("Wrote scratch/previews/slide-01.png ... slide-08.png");
