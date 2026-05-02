from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .schemas import AgentForgeRequest, EvidenceSource


AnswerFamily = Literal[
    "allergies",
    "cardiac",
    "endocrine_metabolic",
    "oncology",
    "red_flags",
    "med_reconciliation",
    "first_room",
    "missing_data",
    "labs",
    "broad_brief",
    "long_tail",
]


@dataclass(frozen=True)
class EvidencePlan:
    answer_family: AnswerFamily
    required_adapters: tuple[str, ...]
    context_adapters: tuple[str, ...] = ()
    preferred_record_types: tuple[str, ...] = ()
    selected_source_ids: tuple[str, ...] = ()
    rubric: tuple[str, ...] = ()

    @property
    def needed_adapters(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.required_adapters, *self.context_adapters)))


def plan_evidence(request: AgentForgeRequest) -> EvidencePlan:
    family = classify_question(request.message)
    selected = _select_sources(request, family)
    required, context, record_types, rubric = _family_policy(family)
    return EvidencePlan(
        answer_family=family,
        required_adapters=required,
        context_adapters=context,
        preferred_record_types=record_types,
        selected_source_ids=tuple(source.id for source in selected),
        rubric=rubric,
    )


def classify_question(message: str) -> AnswerFamily:
    normalized = " ".join(message.lower().split())
    if any(term in normalized for term in ("medication reconciliation", "med rec", "reconciliation")):
        return "med_reconciliation"
    if "missing" in normalized or "before making clinical decisions" in normalized:
        return "missing_data"
    if "lab" in normalized or "labs" in normalized:
        return "labs"
    if "ask the patient first" in normalized or "enter the room" in normalized:
        return "first_room"
    if "red flag" in normalized or "inconsisten" in normalized or "verify" in normalized:
        return "red_flags"
    if any(term in normalized for term in ("oncolog", "cancer", "neoplasm", "malignant")):
        return "oncology"
    if "endocrine" in normalized or "metabolic" in normalized or "cardiometabolic" in normalized:
        return "endocrine_metabolic"
    if any(term in normalized for term in ("cardiac", "heart", "cardiology")):
        return "cardiac"
    if "allerg" in normalized:
        return "allergies"
    if any(term in normalized for term in ("chart brief", "pre-round", "preround", "rounds", "one-minute")):
        return "broad_brief"
    return "long_tail"


def missing_required_adapters(request: AgentForgeRequest, plan: EvidencePlan | None = None) -> list[str]:
    plan = plan or plan_evidence(request)
    statuses = {status.adapter: status.status for status in request.evidence_bundle.adapter_status}
    return [
        adapter
        for adapter in plan.required_adapters
        if statuses.get(adapter) not in {None, "success", "partial"}
    ]


def _family_policy(
    family: AnswerFamily,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    if family == "allergies":
        return (
            ("allergies",),
            ("medications",),
            ("allergy", "medication"),
            (
                "State documented allergies first.",
                "If no drug-like allergy source is present and allergy collection succeeded, say no clear drug allergy is shown in this snapshot.",
                "Mention epinephrine auto-injector or antihistamine evidence only if selected medication evidence supports it.",
            ),
        )
    if family == "cardiac":
        return (
            ("problem_list",),
            ("vitals", "recent_notes"),
            ("problem", "vital", "note"),
            (
                "Separate explicit cardiac diagnoses from risk-related conditions.",
                "If no explicit cardiac diagnosis is selected, say so as a bounded chart-snapshot statement.",
                "Recommend confirming with vitals, notes, and cardiology history without giving treatment directives.",
            ),
        )
    if family == "endocrine_metabolic":
        return (
            ("problem_list",),
            ("labs", "vitals"),
            ("problem", "lab", "vital"),
            (
                "Summarize endocrine/metabolic problem-list evidence and cardiometabolic risk.",
                "If lab trends are not selected or available, say recent labs should be reviewed before management changes.",
            ),
        )
    if family == "oncology":
        return (
            ("problem_list",),
            ("recent_notes",),
            ("problem", "note"),
            (
                "Identify oncology-relevant problem-list evidence.",
                "Ask to verify active disease versus history, treatment timeline, and oncology follow-up.",
            ),
        )
    if family == "red_flags":
        return (
            ("problem_list",),
            ("medications", "recent_notes"),
            ("problem", "medication", "note"),
            (
                "Highlight chart entries that may be historical, resolved, or status-ambiguous.",
                "Do not overstate them as active unless source metadata supports active status.",
            ),
        )
    if family == "med_reconciliation":
        return (
            ("medications",),
            ("medication_history",),
            ("medication",),
            (
                "Distinguish current medication evidence from historical or legacy prescription evidence.",
                "Ask the clinician to reconcile active versus legacy entries before relying on the list.",
            ),
        )
    if family == "first_room":
        return (
            ("problem_list", "allergies", "medications"),
            ("recent_notes", "labs", "vitals"),
            ("problem", "allergy", "medication", "note", "lab", "vital"),
            (
                "Give a concise first-room question sequence grounded in selected chart evidence.",
                "Start with a general symptom-priority question before chart-specific follow-ups.",
                "Prioritize today's symptoms, allergy reaction history, medication use, and status of major diagnoses.",
            ),
        )
    if family == "missing_data":
        return (
            ("problem_list", "allergies", "medications", "vitals", "labs", "recent_notes"),
            (),
            ("problem", "allergy", "medication", "vital", "lab", "note"),
            (
                "Name unavailable or unselected data needed before definitive clinical decisions.",
                "Avoid implying missing data is absent from reality.",
            ),
        )
    if family == "labs":
        return (
            ("labs",),
            (),
            ("lab",),
            (
                "Answer only from selected lab evidence.",
                "If labs are unavailable, say abnormal labs were not found in retrieved lab records and confirm in the chart.",
            ),
        )
    if family == "broad_brief":
        return (
            ("problem_list", "allergies", "medications", "vitals", "labs", "recent_notes"),
            (),
            ("problem", "allergy", "medication", "vital", "lab", "note", "demographic"),
            (
                "Produce a compact pre-round summary with active issues, meds/allergies, objective data, and follow-up gaps.",
                "Do not let one record type crowd out current medications, allergies, or objective data.",
                "Make missing-data caveats concise.",
            ),
        )
    return (
        (),
        ("problem_list", "allergies", "medications", "vitals", "labs", "recent_notes"),
        ("problem", "allergy", "medication", "vital", "lab", "note", "demographic"),
        (
            "Answer the exact question using only selected evidence.",
            "If evidence is insufficient, say what was not found in the retrieved snapshot and what to confirm.",
        ),
    )


def _select_sources(request: AgentForgeRequest, family: AnswerFamily) -> list[EvidenceSource]:
    sources = request.evidence_bundle.sources
    selected: list[EvidenceSource] = []

    def add(matches: list[EvidenceSource], limit: int) -> None:
        added = 0
        for source in _newest_first(matches):
            if added >= limit:
                break
            if source.id not in {item.id for item in selected}:
                selected.append(source)
                added += 1

    if family == "allergies":
        add(_by_type(sources, "allergy"), 8)
        add(_medications_matching(sources, ("epinephrine", "auto-injector", "loratadine", "cetirizine", "fexofenadine", "diphenhydramine")), 4)
    elif family == "cardiac":
        add(_problems_matching(sources, ("cardiac", "heart", "arrhythm", "cad", "chf", "mi", "angina", "hypertension")), 4)
        add(_problems_matching(sources, ("hyperlipid", "prediabetes", "diabetes", "smoking")), 4)
        add(_by_type(sources, "vital"), 4)
        add(_by_type(sources, "note"), 2)
    elif family == "endocrine_metabolic":
        add(_problems_matching(sources, ("prediabetes", "diabetes", "hyperlipid", "dyslipid", "obesity", "thyroid")), 6)
        add(_labs_matching(sources, ("a1c", "glucose", "cholesterol", "ldl", "hdl", "triglyceride", "lipid")), 6)
    elif family == "oncology":
        add(_problems_matching(sources, ("cancer", "neoplasm", "malignant", "carcinoma", "breast")), 6)
        add(_by_type(sources, "note"), 2)
    elif family == "red_flags":
        add(_problems_matching(sources, ("bullet", "miscarriage", "pregnancy", "neoplasm", "malignant")), 6)
        add(_by_type(sources, "medication"), 6)
        add(_by_type(sources, "note"), 2)
    elif family == "med_reconciliation":
        current = [source for source in _by_type(sources, "medication") if source.metadata.get("status", "current") != "historical"]
        historical = [source for source in _by_type(sources, "medication") if source.metadata.get("status") == "historical"]
        add(_medications_matching(current, ("epinephrine", "auto-injector", "loratadine")), 4)
        add(current, 8)
        add(historical, 6)
    elif family == "first_room":
        add(_by_type(sources, "problem"), 3)
        add(_by_type(sources, "medication"), 3)
        add(_by_type(sources, "allergy"), 3)
        add(_by_type(sources, "note"), 2)
        add(_by_type(sources, "vital"), 1)
    elif family == "missing_data":
        add(sources, 10)
    elif family == "labs":
        add(_by_type(sources, "lab"), 8)
    elif family == "broad_brief":
        for record_type, limit in (
            ("problem", 3),
            ("medication", 3),
            ("allergy", 3),
            ("vital", 2),
            ("lab", 2),
            ("note", 2),
        ):
            add(_by_type(sources, record_type), limit)
    else:
        add(sources, 10)

    return selected[:12]


def _by_type(sources: list[EvidenceSource], record_type: str) -> list[EvidenceSource]:
    return [source for source in sources if source.record_type.lower() == record_type]


def _problems_matching(sources: list[EvidenceSource], terms: tuple[str, ...]) -> list[EvidenceSource]:
    return [source for source in _by_type(sources, "problem") if _matches(source, terms)]


def _labs_matching(sources: list[EvidenceSource], terms: tuple[str, ...]) -> list[EvidenceSource]:
    return [source for source in _by_type(sources, "lab") if _matches(source, terms)]


def _medications_matching(sources: list[EvidenceSource], terms: tuple[str, ...]) -> list[EvidenceSource]:
    return [source for source in _by_type(sources, "medication") if _matches(source, terms)]


def _matches(source: EvidenceSource, terms: tuple[str, ...]) -> bool:
    haystack = f"{source.value} {source.field_path} {source.note_span or ''}".lower()
    return any(term in haystack for term in terms)


def _newest_first(sources: list[EvidenceSource]) -> list[EvidenceSource]:
    return sorted(sources, key=lambda source: (source.recorded_at, source.id), reverse=True)
