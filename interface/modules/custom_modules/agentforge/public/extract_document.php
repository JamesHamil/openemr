<?php

/**
 * AgentForge Week 2 extraction endpoint for documents already stored in OpenEMR.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

require_once(__DIR__ . "/../../../../globals.php");
require_once(__DIR__ . "/../../../../../library/classes/Document.class.php");
require_once(__DIR__ . "/../src/AgentForgeOpenEmrCompat.php");
require_once(__DIR__ . "/../src/AgentForgeDocumentStore.php");
require_once(__DIR__ . "/../src/AgentForgeSidecarClient.php");

use OpenEMR\Common\Acl\AclMain;
use OpenEMR\Common\Csrf\CsrfUtils;
use OpenEMR\Common\Logging\EventAuditLogger;
use OpenEMR\Modules\AgentForge\AgentForgeDocumentStore;
use OpenEMR\Modules\AgentForge\AgentForgeSidecarClient;

header('Content-Type: application/json');

$session = agentforge_openemr_session();

try {
    if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
        agentforge_extract_json(agentforge_extract_error('Only POST is supported.', 'method_not_allowed'), 405);
    }

    if (!agentforge_verify_csrf_token((string)($_POST['csrf_token_form'] ?? ''), $session)) {
        CsrfUtils::csrfNotVerified();
    }

    if (!AclMain::aclCheckCore('patients', 'docs')) {
        agentforge_extract_json(agentforge_extract_error('Document access denied.', 'access_denied'), 403);
    }

    $sessionPid = (string)agentforge_session_get($session, 'pid', '');
    $requestPid = (string)($_POST['patient_id'] ?? '');
    if ($sessionPid === '' || $requestPid === '' || $sessionPid !== $requestPid || !ctype_digit($requestPid)) {
        agentforge_extract_json(agentforge_extract_error('Select a valid patient before extracting documents.', 'invalid_patient_context'), 400);
    }

    $documentType = (string)($_POST['document_type'] ?? '');
    if (!in_array($documentType, ['lab_pdf', 'intake_form', 'medication_list'], true)) {
        agentforge_extract_json(agentforge_extract_error('Unsupported AgentForge document type.', 'unsupported_document_type'), 400);
    }

    $openEmrDocumentId = (int)($_POST['openemr_document_id'] ?? 0);
    if ($openEmrDocumentId <= 0) {
        agentforge_extract_json(agentforge_extract_error('Choose an OpenEMR document before extraction.', 'missing_document'), 400);
    }

    $documentRow = sqlQuery(
        "SELECT id, foreign_id, name, mimetype, size FROM documents WHERE id = ? AND deleted = 0",
        [$openEmrDocumentId]
    );
    if (empty($documentRow['id']) || (string)$documentRow['foreign_id'] !== $requestPid) {
        agentforge_extract_json(agentforge_extract_error('Selected document is not available for the active patient.', 'document_not_found'), 404);
    }

    $document = new Document($openEmrDocumentId);
    $content = $document->get_data();
    if ($content === false || $content === '') {
        agentforge_extract_json(agentforge_extract_error('Selected OpenEMR document content was empty or unreadable.', 'empty_document'), 400);
    }

    $size = strlen($content);
    $maxBytes = max(1024 * 128, min((int)(getenv('AGENTFORGE_DOCUMENT_MAX_BYTES') ?: 6291456), 12582912));
    if ($size > $maxBytes) {
        agentforge_extract_json(agentforge_extract_error('Selected document is larger than the AgentForge extraction limit.', 'document_too_large'), 400);
    }

    $filename = basename((string)($documentRow['name'] ?: $document->get_name() ?: $document->get_url_file() ?: ('document-' . $openEmrDocumentId)));
    $mimeType = (string)($documentRow['mimetype'] ?: $document->get_mimetype() ?: 'application/octet-stream');
    $allowed = ['application/pdf', 'image/png', 'image/jpeg', 'text/plain'];
    if (!in_array($mimeType, $allowed, true)) {
        agentforge_extract_json(agentforge_extract_error('Only PDF, PNG, JPEG, or text OpenEMR documents are supported for this demo.', 'unsupported_mime_type'), 400);
    }

    if ($documentType === 'lab_pdf' && $mimeType !== 'application/pdf') {
        agentforge_extract_json(agentforge_extract_error('Lab documents must be OpenEMR PDF documents for the Week 2 flow.', 'lab_pdf_required'), 400);
    }

    $hash = hash('sha256', $content);
    $encounterId = ctype_digit((string)($_POST['encounter_id'] ?? '')) ? (string)$_POST['encounter_id'] : (string)agentforge_session_get($session, 'encounter', '');
    $store = new AgentForgeDocumentStore();
    $previousPayload = $store->loadDocumentExtraction($requestPid, $openEmrDocumentId, $documentType);

    $client = new AgentForgeSidecarClient();
    $extraction = $client->extractDocument(agentforge_build_extraction_request(
        $session,
        $requestPid,
        $encounterId,
        $documentType,
        $openEmrDocumentId,
        $filename,
        $mimeType,
        $content
    ));
    if (empty($extraction['extraction_status'])) {
        $failure = agentforge_extract_unavailable_payload($documentType, $extraction);
        if ($previousPayload !== null && agentforge_extract_fact_count($previousPayload) > 0) {
            $preservedPayload = agentforge_extract_preserve_existing_payload(
                $previousPayload,
                $failure,
                $store->recentDocuments($requestPid)
            );
            EventAuditLogger::getInstance()->newEvent(
                'agentforge-document-extract',
                (string)agentforge_session_get($session, 'authUser', ''),
                (string)agentforge_session_get($session, 'authProvider', ''),
                0,
                'document_id=' . $openEmrDocumentId . ' status=failed_preserved_existing_facts trace_id=' .
                ($failure['trace_id'] ?? 'missing') . ' fact_count=' . agentforge_extract_fact_count($preservedPayload),
                $requestPid
            );
            agentforge_extract_json($preservedPayload);
        }

        EventAuditLogger::getInstance()->newEvent(
            'agentforge-document-extract',
            (string)agentforge_session_get($session, 'authUser', ''),
            (string)agentforge_session_get($session, 'authProvider', ''),
            0,
            'document_id=' . $openEmrDocumentId . ' status=failed trace_id=' . ($failure['trace_id'] ?? 'missing'),
            $requestPid
        );
        agentforge_extract_json([
            'document' => [
                'agentforge_document_id' => 0,
                'openemr_document_id' => $openEmrDocumentId,
                'document_type' => $documentType,
                'filename' => $filename,
                'mime_type' => $mimeType,
                'file_hash' => $hash,
            ],
            'extraction' => $failure,
            'recent_documents' => $store->recentDocuments($requestPid),
        ]);
    }

    $agentforgeDocumentId = $store->createDocumentRecord(
        $requestPid,
        $encounterId,
        $openEmrDocumentId,
        $documentType,
        $filename,
        $mimeType,
        $hash
    );
    $store->replaceFacts($agentforgeDocumentId, $requestPid, $openEmrDocumentId, $extraction);

    EventAuditLogger::getInstance()->newEvent(
        'agentforge-document-extract',
        (string)agentforge_session_get($session, 'authUser', ''),
        (string)agentforge_session_get($session, 'authProvider', ''),
        1,
        'document_id=' . $openEmrDocumentId . ' status=' . ($extraction['extraction_status'] ?? 'unknown') . ' trace_id=' . ($extraction['trace_id'] ?? 'missing'),
        $requestPid
    );

    $payload = $store->loadDocumentExtraction($requestPid, $openEmrDocumentId, $documentType);
    if ($payload === null) {
        $payload = [
            'document' => [
                'agentforge_document_id' => $agentforgeDocumentId,
                'openemr_document_id' => $openEmrDocumentId,
                'document_type' => $documentType,
                'filename' => $filename,
                'mime_type' => $mimeType,
                'file_hash' => $hash,
            ],
            'extraction' => $extraction,
        ];
    }
    $payload['recent_documents'] = $store->recentDocuments($requestPid);
    agentforge_extract_json($payload);
} catch (Throwable $e) {
    EventAuditLogger::getInstance()->newEvent(
        'agentforge-document-extract',
        (string)agentforge_session_get($session, 'authUser', ''),
        (string)agentforge_session_get($session, 'authProvider', ''),
        0,
        'controlled failure=' . $e->getMessage(),
        (string)agentforge_session_get($session, 'pid', '')
    );
    agentforge_extract_json(agentforge_extract_error('Document extraction returned a controlled failure.', 'endpoint_exception'), 500);
}

function agentforge_build_extraction_request($session, string $pid, string $encounterId, string $documentType, int $openEmrDocumentId, string $filename, string $mimeType, string $content): array
{
    return [
        'schema_version' => 'agentforge.document_extract.v1',
        'request_id' => 'doc-req-' . bin2hex(random_bytes(8)),
        'expires_at' => gmdate('c', time() + 300),
        'document_type' => $documentType,
        'source_id' => 'openemr-document-' . $openEmrDocumentId,
        'filename' => $filename,
        'mime_type' => $mimeType,
        'content_base64' => base64_encode($content),
        'text_hint' => $mimeType === 'text/plain' ? substr($content, 0, 8000) : '',
        'scope' => [
            'user_hash' => hash('sha256', (string)agentforge_session_get($session, 'authUser', '')),
            'patient_hash' => hash('sha256', $pid),
            'encounter_hash' => hash('sha256', $encounterId),
            'evidence_bundle_id' => 'document-' . $openEmrDocumentId,
        ],
    ];
}

function agentforge_extract_error(string $message, string $code): array
{
    return [
        'error' => $code,
        'message' => $message,
        'warnings' => [
            [
                'code' => $code,
                'message' => $message,
            ],
        ],
    ];
}

function agentforge_extract_unavailable_payload(string $documentType, array $sidecarResponse): array
{
    return [
        'schema_version' => 'agentforge.document_extract.response.v1',
        'document_type' => $documentType,
        'extraction_status' => 'failed',
        'extracted_facts' => [],
        'warnings' => [
            [
                'code' => 'sidecar_extraction_unavailable',
                'message' => $sidecarResponse['answer'] ?? 'AgentForge sidecar did not return a document extraction response.',
            ],
        ],
        'worker_handoffs' => [],
        'trace_id' => $sidecarResponse['trace_id'] ?? 'extract-unavailable-' . bin2hex(random_bytes(4)),
    ];
}

function agentforge_extract_preserve_existing_payload(array $payload, array $failure, array $recentDocuments): array
{
    if (!isset($payload['extraction']) || !is_array($payload['extraction'])) {
        $payload['extraction'] = [];
    }
    if (!isset($payload['extraction']['warnings']) || !is_array($payload['extraction']['warnings'])) {
        $payload['extraction']['warnings'] = [];
    }
    $payload['extraction']['warnings'][] = [
        'code' => 'sidecar_extraction_unavailable',
        'message' => 'AgentForge extraction failed before new facts were returned; saved facts were preserved.',
        'trace_id' => $failure['trace_id'] ?? '',
    ];
    $payload['preserved_existing_facts'] = true;
    $payload['extraction_attempt'] = $failure;
    $payload['recent_documents'] = $recentDocuments;
    return $payload;
}

function agentforge_extract_fact_count(array $payload): int
{
    $facts = $payload['extraction']['extracted_facts'] ?? [];
    return is_array($facts) ? count($facts) : 0;
}

function agentforge_extract_json(array $payload, int $status = 200): void
{
    http_response_code($status);
    echo json_encode($payload);
    exit;
}
