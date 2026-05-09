import base64
from pathlib import Path
import unittest

from agentforge_sidecar.document_extraction import _normalize_bounding_box, _normalize_fact, extract_document
from agentforge_sidecar.schemas import DocumentExtractionRequest, ExtractedFact, SourceCitation
from agentforge_sidecar.settings import Settings


def _request() -> DocumentExtractionRequest:
    return DocumentExtractionRequest(
        schema_version="agentforge.document_extract.v1",
        request_id="doc-test",
        expires_at="2026-05-07T12:00:00Z",
        document_type="lab_pdf",
        source_id="openemr-document-7",
        filename="lab.pdf",
        mime_type="application/pdf",
        content_base64=base64.b64encode(b"Potassium 5.8 mmol/L").decode("ascii"),
        text_hint="Potassium 5.8 mmol/L",
        scope={
            "user_hash": "user",
            "patient_hash": "patient",
            "encounter_hash": "encounter",
            "evidence_bundle_id": "document-7",
        },
    )


def _fact(box, page_or_section: str = "page 2") -> ExtractedFact:
    return ExtractedFact(
        fact_type="lab_result",
        label="Potassium",
        value="5.8",
        unit="mmol/L",
        abnormal_flag="high",
        confidence=0.92,
        citation=SourceCitation(
            source_type="lab_pdf",
            source_id="openemr-document-7",
            page_or_section=page_or_section,
            field_or_chunk_id="potassium",
            quote_or_value="Potassium 5.8 mmol/L",
            bounding_box=box,
        ),
    )


class DocumentExtractionCitationTest(unittest.TestCase):
    def test_valid_bounding_box_is_preserved_with_page(self):
        normalized = _normalize_fact(
            _request(),
            _fact({"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.04, "page": 4}),
            0,
        )

        self.assertEqual(
            normalized.citation.bounding_box,
            {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.04, "page": 4},
        )

    def test_bounding_box_is_clamped_and_page_defaults_from_citation(self):
        normalized = _normalize_fact(
            _request(),
            _fact({"x": -0.25, "y": 0.8, "width": 1.5, "height": 0.5}),
            0,
        )

        box = normalized.citation.bounding_box or {}
        self.assertEqual(box.get("x"), 0.0)
        self.assertEqual(box.get("y"), 0.8)
        self.assertEqual(box.get("width"), 1.0)
        self.assertAlmostEqual(float(box.get("height", 0)), 0.2)
        self.assertEqual(box.get("page"), 2)

    def test_incomplete_or_non_numeric_bounding_box_is_dropped(self):
        incomplete = _normalize_fact(_request(), _fact({"x": 0.1, "y": 0.2, "width": 0.3}), 0)
        non_numeric = _normalize_bounding_box({"x": 0.1, "y": "top", "width": 0.3, "height": 0.1})

        self.assertIsNone(incomplete.citation.bounding_box)
        self.assertIsNone(non_numeric)

    def test_textual_citation_survives_when_box_is_removed(self):
        normalized = _normalize_fact(_request(), _fact({"x": 1.0, "y": 0.5, "width": 0.5, "height": 0.1}), 0)

        self.assertIsNone(normalized.citation.bounding_box)
        self.assertEqual(normalized.citation.page_or_section, "page 2")
        self.assertEqual(normalized.citation.field_or_chunk_id, "potassium")
        self.assertEqual(normalized.citation.quote_or_value, "Potassium 5.8 mmol/L")

    def test_document_viewer_contains_citation_preview_wiring(self):
        template = Path(__file__).resolve().parents[3] / "templates" / "documents" / "general_view.html"
        source = template.read_text()

        self.assertIn('value="medication_list"', source)
        self.assertIn("Medication List", source)
        self.assertIn("agentforgeCitationPreview", source)
        self.assertIn("hasAgentForgeBoundingBox", source)
        self.assertIn("hasAgentForgePreviewableCitation", source)
        self.assertIn("isAgentForgePdfDocument", source)
        self.assertIn("agentforgeDocumentName", source)
        self.assertIn("agentforge-fact-workspace", source)
        self.assertIn("document_facts.php", source)
        self.assertIn("loadAgentForgeStoredFacts(docid, agentforgePatientId)", source)
        self.assertIn("beginAgentForgeFactEdit", source)
        self.assertIn("saveAgentForgeFacts", source)
        self.assertIn("Re-extracting will replace any manual edits", source)
        self.assertIn("UI text-aligned highlight", source)
        self.assertIn("renderAgentForgeCitationPreview(agentForgeCurrentFacts[firstPreviewableIndex]", source)
        self.assertIn("pdfjsLib.getDocument", source)
        self.assertIn("agentforge-preview-link", source)

    def test_php_store_preserves_citation_json(self):
        store = (
            Path(__file__).resolve().parents[3]
            / "interface"
            / "modules"
            / "custom_modules"
            / "agentforge"
            / "src"
            / "AgentForgeDocumentStore.php"
        )
        source = store.read_text()

        self.assertIn("citation_json", source)
        self.assertIn("json_encode($citation", source)
        self.assertIn("loadDocumentExtraction", source)
        self.assertIn("saveEditedFacts", source)

    def test_document_facts_endpoint_supports_load_and_save(self):
        endpoint = (
            Path(__file__).resolve().parents[3]
            / "interface"
            / "modules"
            / "custom_modules"
            / "agentforge"
            / "public"
            / "document_facts.php"
        )
        source = endpoint.read_text()

        self.assertIn("action", source)
        self.assertIn("'load'", source)
        self.assertIn("'save'", source)
        self.assertIn("saveEditedFacts", source)
        self.assertIn("agentforge-document-facts-save", source)

    def test_medication_list_mock_extraction_returns_medication_facts(self):
        request = _request().model_copy(
            update={
                "document_type": "medication_list",
                "filename": "medication-list.txt",
                "mime_type": "text/plain",
                "content_base64": base64.b64encode(
                    b"Metformin 500 mg by mouth twice daily\nLisinopril 10 mg daily"
                ).decode("ascii"),
                "text_hint": "Metformin 500 mg by mouth twice daily\nLisinopril 10 mg daily",
            }
        )

        response, trace = extract_document(request, Settings(mode="mock"))

        self.assertEqual(response.document_type, "medication_list")
        self.assertEqual(response.extraction_status, "success")
        labels = [fact.label for fact in response.extracted_facts]
        self.assertIn("Metformin", labels)
        self.assertIn("Lisinopril", labels)
        self.assertTrue(all(fact.fact_type == "medication" for fact in response.extracted_facts))
        self.assertEqual(response.extracted_facts[0].citation.page_or_section, "medication list")
        self.assertEqual(trace["mode"], "mock")


if __name__ == "__main__":
    unittest.main()
