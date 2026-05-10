<?php

/**
 * AgentForge stored document facts endpoint.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

require_once(__DIR__ . "/../../../../globals.php");
require_once(__DIR__ . "/../src/AgentForgeOpenEmrCompat.php");
require_once(__DIR__ . "/../src/AgentForgeChartWritebackService.php");
require_once(__DIR__ . "/../src/AgentForgeDocumentStore.php");

use OpenEMR\Common\Acl\AclMain;
use OpenEMR\Common\Csrf\CsrfUtils;
use OpenEMR\Common\Logging\EventAuditLogger;
use OpenEMR\Modules\AgentForge\AgentForgeChartWritebackService;
use OpenEMR\Modules\AgentForge\AgentForgeDocumentStore;

header('Content-Type: application/json');

$session = agentforge_openemr_session();

try {
    if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
        agentforge_document_facts_json(agentforge_document_facts_error('Only POST is supported.', 'method_not_allowed'), 405);
    }

    if (!agentforge_verify_csrf_token((string)($_POST['csrf_token_form'] ?? ''), $session)) {
        CsrfUtils::csrfNotVerified();
    }

    if (!AclMain::aclCheckCore('patients', 'docs')) {
        agentforge_document_facts_json(agentforge_document_facts_error('Document access denied.', 'access_denied'), 403);
    }

    $sessionPid = (string)agentforge_session_get($session, 'pid', '');
    $requestPid = (string)($_POST['patient_id'] ?? '');
    if ($sessionPid === '' || $requestPid === '' || $sessionPid !== $requestPid || !ctype_digit($requestPid)) {
        agentforge_document_facts_json(agentforge_document_facts_error('Select a valid patient before managing document facts.', 'invalid_patient_context'), 400);
    }

    $action = (string)($_POST['action'] ?? '');
    if (!in_array($action, ['load', 'save'], true)) {
        agentforge_document_facts_json(agentforge_document_facts_error('Unsupported document facts action.', 'unsupported_action'), 400);
    }

    $documentType = trim((string)($_POST['document_type'] ?? ''));
    if ($documentType !== '' && !in_array($documentType, ['lab_pdf', 'intake_form', 'medication_list'], true)) {
        agentforge_document_facts_json(agentforge_document_facts_error('Unsupported AgentForge document type.', 'unsupported_document_type'), 400);
    }

    $openEmrDocumentId = (int)($_POST['openemr_document_id'] ?? 0);
    if ($openEmrDocumentId <= 0) {
        agentforge_document_facts_json(agentforge_document_facts_error('Choose an OpenEMR document before managing facts.', 'missing_document'), 400);
    }

    $documentRow = sqlQuery(
        "SELECT id, foreign_id, name, mimetype, hash FROM documents WHERE id = ? AND deleted = 0",
        [$openEmrDocumentId]
    );
    if (empty($documentRow['id']) || (string)$documentRow['foreign_id'] !== $requestPid) {
        agentforge_document_facts_json(agentforge_document_facts_error('Selected document is not available for the active patient.', 'document_not_found'), 404);
    }

    $store = new AgentForgeDocumentStore();

    if ($action === 'load') {
        $payload = $store->loadDocumentExtraction($requestPid, $openEmrDocumentId, $documentType);
        if ($payload === null) {
            agentforge_document_facts_json([
                'empty' => true,
                'message' => 'No saved AgentForge facts were found for this document.',
                'document' => [
                    'openemr_document_id' => $openEmrDocumentId,
                    'document_type' => $documentType,
                    'filename' => (string)($documentRow['name'] ?? ''),
                    'mime_type' => (string)($documentRow['mimetype'] ?? ''),
                ],
            ]);
        }
        $payload['recent_documents'] = $store->recentDocuments($requestPid);
        agentforge_document_facts_json($payload);
    }

    $factsJson = (string)($_POST['facts_json'] ?? '');
    $facts = json_decode($factsJson, true);
    if (!is_array($facts)) {
        agentforge_document_facts_json(agentforge_document_facts_error('Edited facts payload was not valid JSON.', 'invalid_facts_json'), 400);
    }
    if (count($facts) > 200) {
        agentforge_document_facts_json(agentforge_document_facts_error('Too many edited facts were submitted.', 'too_many_facts'), 400);
    }

    $existingPayload = $store->loadDocumentExtraction($requestPid, $openEmrDocumentId, $documentType);
    if ($documentType === '' && is_array($existingPayload)) {
        $documentType = (string)($existingPayload['document']['document_type'] ?? '');
    }
    if (!in_array($documentType, ['lab_pdf', 'intake_form', 'medication_list'], true)) {
        agentforge_document_facts_json(agentforge_document_facts_error('Choose an AgentForge document type before saving facts.', 'missing_document_type'), 400);
    }

    $agentforgeDocumentId = (int)($existingPayload['document']['agentforge_document_id'] ?? 0);
    if ($agentforgeDocumentId <= 0) {
        $filename = basename((string)($documentRow['name'] ?: ('document-' . $openEmrDocumentId)));
        $mimeType = (string)($documentRow['mimetype'] ?: 'application/octet-stream');
        $storedHash = trim((string)($documentRow['hash'] ?? ''));
        $fileHash = strlen($storedHash) === 64 ? $storedHash : hash('sha256', $storedHash . '|' . $openEmrDocumentId . '|' . $filename);
        $encounterId = ctype_digit((string)($_POST['encounter_id'] ?? '')) ? (string)$_POST['encounter_id'] : (string)agentforge_session_get($session, 'encounter', '');
        $agentforgeDocumentId = $store->createDocumentRecord(
            $requestPid,
            $encounterId,
            $openEmrDocumentId,
            $documentType,
            $filename,
            $mimeType,
            $fileHash
        );
    }

    $traceId = 'manual-save-' . bin2hex(random_bytes(4));
    $store->saveEditedFacts($agentforgeDocumentId, $requestPid, $openEmrDocumentId, $documentType, $facts, $traceId);
    $payload = $store->loadDocumentExtraction($requestPid, $openEmrDocumentId, $documentType);
    if ($payload === null) {
        agentforge_document_facts_json(agentforge_document_facts_error('Saved facts could not be reloaded.', 'reload_failed'), 500);
    }
    $payload['chart_writeback'] = (new AgentForgeChartWritebackService())->writeBack(
        $requestPid,
        $agentforgeDocumentId,
        $openEmrDocumentId,
        $payload
    );
    $payload['recent_documents'] = $store->recentDocuments($requestPid);

    EventAuditLogger::getInstance()->newEvent(
        'agentforge-document-facts-save',
        (string)agentforge_session_get($session, 'authUser', ''),
        (string)agentforge_session_get($session, 'authProvider', ''),
        1,
        'document_id=' . $openEmrDocumentId . ' fact_count=' . count($facts) . ' trace_id=' . $traceId,
        $requestPid
    );

    agentforge_document_facts_json($payload);
} catch (Throwable $e) {
    EventAuditLogger::getInstance()->newEvent(
        'agentforge-document-facts-save',
        (string)agentforge_session_get($session, 'authUser', ''),
        (string)agentforge_session_get($session, 'authProvider', ''),
        0,
        'controlled failure=' . $e->getMessage(),
        (string)agentforge_session_get($session, 'pid', '')
    );
    agentforge_document_facts_json(agentforge_document_facts_error('Document facts request returned a controlled failure.', 'endpoint_exception'), 500);
}

function agentforge_document_facts_error(string $message, string $code): array
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

function agentforge_document_facts_json(array $payload, int $status = 200): void
{
    http_response_code($status);
    echo json_encode($payload);
    exit;
}
