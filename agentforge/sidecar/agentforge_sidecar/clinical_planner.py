from __future__ import annotations

import json
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
    "change_since_review",
    "document_facts",
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
    secondary_families: tuple[AnswerFamily, ...] = ()
    confidence: float = 1.0

    @property
    def needed_adapters(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.required_adapters, *self.context_adapters)))


def plan_evidence(request: AgentForgeRequest) -> EvidencePlan:
    family = classify_question(request.message)
    secondary_families = _secondary_families(request.message, family)
    selected = _select_sources(request, family, secondary_families)
    required, context, record_types, rubric = _combined_family_policy(family, secondary_families)
    return EvidencePlan(
        answer_family=family,
        required_adapters=required,
        context_adapters=context,
        preferred_record_types=record_types,
        selected_source_ids=tuple(source.id for source in selected),
        rubric=rubric,
        secondary_families=secondary_families,
        confidence=_planner_confidence(request.message, family, secondary_families),
    )


def classify_question(message: str) -> AnswerFamily:
    normalized = " ".join(message.lower().split())
    if any(term in normalized for term in ("what changed", "changed since", "since last review")):
        return "change_since_review"
    if "missing" in normalized or "before making clinical decisions" in normalized:
        return "missing_data"
    if _is_document_fact_question(normalized) and not _is_lab_question(normalized):
        return "document_facts"
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
    if any(
        term in normalized
        for term in (
            "cardiac",
            "heart",
            "cardiology",
            "ascvd",
            "cardiovascular",
            "cv risk",
            "bp",
            "blood pressure",
        )
    ):
        return "cardiac"
    if any(
        term in normalized
        for term in (
            "allerg",
            "atopy",
            "reaction",
            "sensitivity",
            "anaphylaxis",
            "contraindication",
            "contraindicated",
            "anything i should avoid",
            "safe to give",
            "before i prescribe",
        )
    ):
        return "allergies"
    if any(
        term in normalized
        for term in (
            "medication reconciliation",
            "med rec",
            "reconciliation",
            "current meds",
            "current medications",
            "what meds",
            "which meds",
            "medications",
        )
    ):
        return "med_reconciliation"
    if any(
        term in normalized
        for term in (
            "chart brief",
            "pre-round",
            "preround",
            "rounds",
            "one-minute",
            "what's going on",
            "what is going on",
            "anything concerning",
            "most important",
            "prioritize",
            "how should i think",
        )
    ):
        return "broad_brief"
    return "long_tail"


def _secondary_families(message: str, primary: AnswerFamily) -> tuple[AnswerFamily, ...]:
    normalized = " ".join(message.lower().split())
    secondary: list[AnswerFamily] = []

    def add(family: AnswerFamily, terms: tuple[str, ...]) -> None:
        if family == primary or family in secondary:
            return
        if any(term in normalized for term in terms):
            secondary.append(family)

    add("oncology", ("oncolog", "cancer", "neoplasm", "malignant"))
    add("med_reconciliation", ("current meds", "current medications", "meds", "medications"))
    add("allergies", ("allerg", "atopy", "reaction", "sensitivity", "anaphylaxis"))
    add("cardiac", ("ascvd", "cardiac", "heart", "cardiovascular", "bp", "blood pressure"))
    add("endocrine_metabolic", ("endocrine", "metabolic", "cardiometabolic", "diabetes", "prediabetes", "lipid"))
    add("change_since_review", ("what changed", "changed since", "since last review", "trajectory", "overnight", "worse", "improved"))
    return tuple(secondary[:3])


def _planner_confidence(message: str, family: AnswerFamily, secondary_families: tuple[AnswerFamily, ...]) -> float:
    if family == "long_tail":
        return 0.3
    if secondary_families:
        return 0.85
    if family == "broad_brief" and any(
        term in " ".join(message.lower().split())
        for term in ("what's going on", "what is going on", "anything concerning", "how should i think")
    ):
        return 0.65
    return 0.95


def _is_document_fact_question(normalized: str) -> bool:
    direct_terms = (
        "document fact",
        "extracted fact",
        "extracted facts",
        "intake",
        "intake form",
        "uploaded document",
        "uploaded documents",
        "uploaded pdf",
        "pdf",
        "form",
        "medication list",
        "med list",
        "paperwork",
    )
    if any(term in normalized for term in direct_terms):
        return True
    field_terms = (
        "phone",
        "contact number",
        "emergency contact",
        "preferred pharmacy",
        "pharmacy",
        "insurance",
        "policy number",
        "group number",
        "signature",
        "signed",
        "address",
        "email",
        "social history",
        "recreational drug",
        "recreational drugs",
        "alcohol",
    )
    return any(term in normalized for term in field_terms)


def _is_lab_question(normalized: str) -> bool:
    return any(term in normalized for term in ("lab", "labs", "cbc", "blood count", "glucose", "creatinine", "a1c"))


def missing_required_adapters(request: AgentForgeRequest, plan: EvidencePlan | None = None) -> list[str]:
    plan = plan or plan_evidence(request)
    statuses = {status.adapter: status.status for status in request.evidence_bundle.adapter_status}
    missing: list[str] = []
    for adapter in plan.required_adapters:
        if statuses.get(adapter) in {None, "success", "partial"}:
            continue
        if adapter == "labs" and _has_lab_document_evidence(request):
            continue
        if adapter == "medications" and _has_medication_document_evidence(request):
            continue
        missing.append(adapter)
    return missing


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
            ("medication", "document_fact"),
            (
                "Distinguish current medication evidence from historical or legacy prescription evidence.",
                "Use uploaded medication-list document facts when they are the selected medication evidence.",
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
    if family == "change_since_review":
        return (
            ("recent_notes",),
            (),
            ("note",),
            (
                "Compare selected recent note evidence for clinically relevant changes since the last review.",
                "Preserve direction and timing language from notes, such as improved, worsened, overnight, or this morning.",
                "If notes conflict, say they conflict and ask the clinician to confirm the latest status.",
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
    if family == "document_facts":
        return (
            ("agentforge_documents",),
            (),
            ("document_fact", "demographic"),
            (
                "Answer directly from selected extracted document facts.",
                "Do not include unrelated chart inventory or unrelated collector gaps.",
                "If the question is about an intake form, stay within intake-form document facts.",
                "Use demographic sources only when the question asks for patient identity or demographics.",
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


def _combined_family_policy(
    family: AnswerFamily, secondary_families: tuple[AnswerFamily, ...]
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    required: list[str] = []
    context: list[str] = []
    record_types: list[str] = []
    rubric: list[str] = []

    for item in (family, *secondary_families):
        item_required, item_context, item_record_types, item_rubric = _family_policy(item)
        required.extend(item_required)
        context.extend(item_context)
        record_types.extend(item_record_types)
        rubric.extend(item_rubric)

    return (
        tuple(dict.fromkeys(required)),
        tuple(dict.fromkeys(context)),
        tuple(dict.fromkeys(record_types)),
        tuple(dict.fromkeys(rubric)),
    )


def _select_sources(
    request: AgentForgeRequest, family: AnswerFamily, secondary_families: tuple[AnswerFamily, ...] = ()
) -> list[EvidenceSource]:
    selected: list[EvidenceSource] = []
    for item in (family, *secondary_families):
        for source in _select_sources_for_family(request, item):
            if source.id not in {existing.id for existing in selected}:
                selected.append(source)
            if len(selected) >= 12:
                return selected
    return selected


def _select_sources_for_family(request: AgentForgeRequest, family: AnswerFamily) -> list[EvidenceSource]:
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
        add(_medication_document_fact_sources(sources), 8)
        add(historical, 6)
    elif family == "first_room":
        add(_by_type(sources, "problem"), 3)
        add(_by_type(sources, "medication"), 3)
        add(_by_type(sources, "allergy"), 3)
        add(_by_type(sources, "note"), 2)
        add(_by_type(sources, "vital"), 1)
    elif family == "missing_data":
        add(sources, 10)
    elif family == "change_since_review":
        add(_by_type(sources, "note"), 8)
    elif family == "labs":
        add(_by_type(sources, "lab"), 8)
        add(_lab_document_fact_sources(sources), 8)
    elif family == "document_facts":
        add(_document_fact_sources_for_message(request), 10)
        if _asks_patient_identity(request.message):
            add(_by_type(sources, "demographic"), 3)
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


LAB_DOCUMENT_FACT_TERMS = (
    "lab",
    "labs",
    "cbc",
    "blood count",
    "differential",
    "morphology",
    "smear",
    "glucose",
    "creatinine",
    "a1c",
    "hemoglobin",
    "hematocrit",
    "platelet",
    "leukocyte",
    "lymphocyte",
    "monocyte",
    "neutrophil",
    "blast",
    "promyelocyte",
    "metamyelocyte",
)


def _lab_document_fact_sources(sources: list[EvidenceSource]) -> list[EvidenceSource]:
    return [source for source in _by_type(sources, "document_fact") if _is_lab_document_fact(source)]


def _is_lab_document_fact(source: EvidenceSource) -> bool:
    if source.record_type != "document_fact":
        return False
    if _document_type(source) == "lab_pdf":
        return True
    if "lab_result" in source.field_path.lower():
        return True
    return _matches(source, LAB_DOCUMENT_FACT_TERMS)


def _has_lab_document_evidence(request: AgentForgeRequest) -> bool:
    statuses = {status.adapter: status.status for status in request.evidence_bundle.adapter_status}
    documents_available = statuses.get("agentforge_documents") in {None, "success", "partial"}
    return documents_available and any(
        _is_lab_document_fact(source) for source in request.evidence_bundle.sources
    )


MEDICATION_DOCUMENT_FACT_TERMS = (
    "medication",
    "medications",
    "med",
    "meds",
    "drug",
    "dose",
    "dosage",
    "frequency",
    "route",
    "sig",
    "prescriber",
    "metformin",
    "lisinopril",
    "atorvastatin",
    "amlodipine",
    "insulin",
)


def _medication_document_fact_sources(sources: list[EvidenceSource]) -> list[EvidenceSource]:
    return [source for source in _by_type(sources, "document_fact") if _is_medication_document_fact(source)]


def _is_medication_document_fact(source: EvidenceSource) -> bool:
    if source.record_type != "document_fact":
        return False
    if _document_type(source) == "medication_list":
        return True
    if "medication" in source.field_path.lower():
        return True
    return _matches(source, MEDICATION_DOCUMENT_FACT_TERMS)


def _has_medication_document_evidence(request: AgentForgeRequest) -> bool:
    statuses = {status.adapter: status.status for status in request.evidence_bundle.adapter_status}
    documents_available = statuses.get("agentforge_documents") in {None, "success", "partial"}
    return documents_available and any(
        _is_medication_document_fact(source) for source in request.evidence_bundle.sources
    )


def _medications_matching(sources: list[EvidenceSource], terms: tuple[str, ...]) -> list[EvidenceSource]:
    return [source for source in _by_type(sources, "medication") if _matches(source, terms)]


def _document_fact_sources_for_message(request: AgentForgeRequest) -> list[EvidenceSource]:
    normalized = " ".join(request.message.lower().split())
    sources = _by_type(request.evidence_bundle.sources, "document_fact")
    if not sources:
        return []

    if "medication list" in normalized or "med list" in normalized:
        medication_list_sources = [source for source in sources if _document_type(source) == "medication_list"]
        if medication_list_sources:
            sources = medication_list_sources
    elif "intake" in normalized or "form" in normalized:
        intake_sources = [source for source in sources if _document_type(source) in {"intake_form", ""}]
        if intake_sources:
            sources = intake_sources

    matched = [source for source in sources if _document_fact_matches_message(source, normalized)]
    return matched or sources


def _document_fact_matches_message(source: EvidenceSource, normalized_message: str) -> bool:
    field_terms_by_topic = {
        "phone": ("phone", "number", "contact"),
        "contact": ("contact", "emergency"),
        "emergency": ("emergency", "contact"),
        "pharmacy": ("pharmacy", "medimart"),
        "insurance": ("insurance", "policy", "group", "provider"),
        "signature": ("signature", "signed"),
        "date": ("date",),
        "address": ("address",),
        "email": ("email",),
        "medication": ("medication", "med", "dose", "dosage", "frequency", "route", "prescriber"),
        "med": ("medication", "med", "dose", "dosage", "frequency", "route", "prescriber"),
        "social": ("social", "alcohol", "tobacco", "recreational", "drug"),
        "alcohol": ("alcohol",),
        "recreational": ("recreational", "drug"),
    }
    query_topics = {
        topic
        for topic in field_terms_by_topic
        if topic in normalized_message
    }
    if not query_topics:
        return True

    haystack = _document_fact_haystack(source)
    return any(any(term in haystack for term in field_terms_by_topic[topic]) for topic in query_topics)


def _document_fact_haystack(source: EvidenceSource) -> str:
    return " ".join(
        [
            source.field_path,
            source.value,
            source.note_span or "",
            " ".join(str(value) for value in source.metadata.values()),
        ]
    ).lower()


def _document_type(source: EvidenceSource) -> str:
    document_type = str(source.metadata.get("document_type", "")).lower()
    if document_type:
        return document_type
    raw_citation = source.metadata.get("citation", "")
    if not raw_citation:
        return ""
    try:
        citation = json.loads(raw_citation)
    except (TypeError, ValueError):
        return ""
    return str(citation.get("document_type", "")).lower() if isinstance(citation, dict) else ""


def _asks_patient_identity(message: str) -> bool:
    normalized = " ".join(message.lower().split())
    return any(
        term in normalized
        for term in (
            "who is",
            "patient identity",
            "identify the patient",
            "patient name",
            "name",
            "dob",
            "date of birth",
            "sex",
            "gender",
            "demographic",
            "demographics",
        )
    )


def _matches(source: EvidenceSource, terms: tuple[str, ...]) -> bool:
    haystack = f"{source.value} {source.field_path} {source.note_span or ''}".lower()
    return any(term in haystack for term in terms)


def _newest_first(sources: list[EvidenceSource]) -> list[EvidenceSource]:
    return sorted(sources, key=lambda source: (source.recorded_at, source.id), reverse=True)
