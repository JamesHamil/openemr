import base64
from pathlib import Path
import unittest

from agentforge_sidecar.document_extraction import _normalize_bounding_box, _normalize_fact
from agentforge_sidecar.schemas import DocumentExtractionRequest, ExtractedFact, SourceCitation


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

        self.assertIn("agentforgeCitationPreview", source)
        self.assertIn("hasAgentForgeBoundingBox", source)
        self.assertIn("hasAgentForgePreviewableCitation", source)
        self.assertIn("page rendered; exact quote location was not found", source)
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


if __name__ == "__main__":
    unittest.main()
