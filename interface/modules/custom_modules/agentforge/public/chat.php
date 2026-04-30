<?php

/**
 * AgentForge Clinical Co-Pilot chat endpoint.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

require_once(__DIR__ . "/../../../../globals.php");
require_once(__DIR__ . "/../src/AgentForgeOpenEmrCompat.php");
require_once(__DIR__ . "/../src/AgentForgeEvidenceCollector.php");
require_once(__DIR__ . "/../src/AgentForgeSidecarClient.php");

use OpenEMR\Common\Acl\AclMain;
use OpenEMR\Common\Csrf\CsrfUtils;
use OpenEMR\Common\Logging\EventAuditLogger;
use OpenEMR\Modules\AgentForge\AgentForgeEvidenceCollector;
use OpenEMR\Modules\AgentForge\AgentForgeSidecarClient;

header('Content-Type: application/json');

$session = agentforge_openemr_session();

try {
    if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
        agentforge_json_response(agentforge_error_response('Only POST is supported.', 'method_not_allowed'), 405);
    }

    if (!agentforge_verify_csrf_token((string)($_POST['csrf_token_form'] ?? ''), $session)) {
        CsrfUtils::csrfNotVerified();
    }

    if (!AclMain::aclCheckCore('patients', 'demo') && !AclMain::aclCheckCore('patients', 'med') && !AclMain::aclCheckCore('patients', 'notes')) {
        agentforge_json_response(agentforge_error_response('Access denied.', 'access_denied', 'refused'), 403);
    }

    $sessionPid = (string)agentforge_session_get($session, 'pid', '');
    $requestPid = (string)($_POST['patient_id'] ?? '');
    if ($sessionPid === '' || $requestPid === '' || $sessionPid !== $requestPid || !ctype_digit($requestPid)) {
        agentforge_json_response(agentforge_error_response('Select a valid patient in OpenEMR before using Clinical Co-Pilot.', 'invalid_patient_context', 'refused'), 400);
    }

    $lastRequestAt = (int)agentforge_session_get($session, 'agentforge_last_request_at', 0);
    if ($lastRequestAt > 0 && (time() - $lastRequestAt) < 2) {
        agentforge_json_response(agentforge_error_response('Rate limit exceeded. Please retry in a moment.', 'rate_limited', 'failed'), 429);
    }
    agentforge_session_set($session, 'agentforge_last_request_at', time());

    $message = trim((string)($_POST['message'] ?? ''));
    if ($message === '') {
        $message = 'Give me a chart brief for rounds.';
    }

    $encounterId = ctype_digit((string)($_POST['encounter_id'] ?? '')) ? (string)$_POST['encounter_id'] : (string)agentforge_session_get($session, 'encounter', '');
    $conversationId = trim((string)($_POST['conversation_id'] ?? ''));
    if ($conversationId === '') {
        $conversationId = 'rounding-' . $requestPid;
    }

    $collector = new AgentForgeEvidenceCollector();
    $bundle = $collector->collect($requestPid, $encounterId);
    $cacheKey = agentforge_cache_key($requestPid, $encounterId, $message, $bundle);
    $cachedResponse = agentforge_cache_get($session, $cacheKey);
    if (is_array($cachedResponse)) {
        EventAuditLogger::getInstance()->newEvent(
            'agentforge-chart-brief',
            (string)agentforge_session_get($session, 'authUser', ''),
            (string)agentforge_session_get($session, 'authProvider', ''),
            1,
            'cache_hit=1 trace_id=' . ($cachedResponse['trace_id'] ?? 'missing') . ' status=' . ($cachedResponse['verification_status'] ?? 'unknown'),
            $requestPid
        );
        agentforge_json_response($cachedResponse);
    }

    $request = agentforge_build_request($session, $conversationId, $message, $bundle);

    $client = new AgentForgeSidecarClient();
    $response = $client->send($request);
    agentforge_cache_set($session, $cacheKey, $response);

    EventAuditLogger::getInstance()->newEvent(
        'agentforge-chart-brief',
        (string)agentforge_session_get($session, 'authUser', ''),
        (string)agentforge_session_get($session, 'authProvider', ''),
        1,
        'trace_id=' . ($response['trace_id'] ?? 'missing') . ' status=' . ($response['verification_status'] ?? 'unknown'),
        $requestPid
    );

    agentforge_json_response($response);
} catch (Throwable $e) {
    EventAuditLogger::getInstance()->newEvent(
        'agentforge-chart-brief',
        (string)agentforge_session_get($session, 'authUser', ''),
        (string)agentforge_session_get($session, 'authProvider', ''),
        0,
        'controlled failure=' . $e->getMessage(),
        (string)agentforge_session_get($session, 'pid', '')
    );
    agentforge_json_response(agentforge_error_response('Clinical Co-Pilot returned a controlled failure.', 'endpoint_exception'), 500);
}

function agentforge_build_request($session, string $conversationId, string $message, array $bundle): array
{
    $pid = (string)$bundle['patient_context']['patient_id'];
    $encounterId = (string)$bundle['patient_context']['encounter_id'];
    return [
        'schema_version' => 'agentforge.request.v1',
        'request_id' => 'req-' . bin2hex(random_bytes(8)),
        'conversation_id' => $conversationId,
        'expires_at' => gmdate('c', time() + 300),
        'purpose' => 'patient_rounding_brief',
        'scope' => [
            'user_hash' => hash('sha256', (string)agentforge_session_get($session, 'authUser', '')),
            'patient_hash' => hash('sha256', $pid),
            'encounter_hash' => hash('sha256', $encounterId),
            'evidence_bundle_id' => (string)$bundle['id'],
        ],
        'message' => $message,
        'evidence_bundle' => $bundle,
    ];
}

function agentforge_error_response(string $message, string $code, string $status = 'failed'): array
{
    return [
        'schema_version' => 'agentforge.response.v1',
        'answer' => $message,
        'sections' => [],
        'claims' => [],
        'sources' => [],
        'warnings' => [
            [
                'code' => $code,
                'message' => $message,
            ],
        ],
        'blocked_claims' => [],
        'verification_status' => $status,
        'trace_id' => 'openemr-' . bin2hex(random_bytes(4)),
    ];
}

function agentforge_cache_key(string $pid, string $encounterId, string $message, array $bundle): string
{
    $fingerprintPayload = [
        'sources' => $bundle['sources'] ?? [],
        'adapter_status' => $bundle['adapter_status'] ?? [],
    ];
    $fingerprint = hash('sha256', json_encode($fingerprintPayload, JSON_UNESCAPED_SLASHES));
    $normalizedMessage = preg_replace('/\s+/', ' ', strtolower(trim($message)));
    return hash('sha256', $pid . '|' . $encounterId . '|' . $normalizedMessage . '|' . $fingerprint);
}

function agentforge_cache_get($session, string $key): ?array
{
    $cache = agentforge_session_get($session, 'agentforge_response_cache', []);
    if (!is_array($cache) || empty($cache[$key]) || !is_array($cache[$key])) {
        return null;
    }
    if ((int)($cache[$key]['expires_at'] ?? 0) < time()) {
        unset($cache[$key]);
        agentforge_session_set($session, 'agentforge_response_cache', $cache);
        return null;
    }
    $response = $cache[$key]['response'] ?? null;
    return is_array($response) ? $response : null;
}

function agentforge_cache_set($session, string $key, array $response): void
{
    if (!in_array($response['verification_status'] ?? '', ['verified', 'partial', 'refused'], true)) {
        return;
    }
    $ttl = max(30, min((int)(getenv('AGENTFORGE_CACHE_TTL_SECONDS') ?: 300), 900));
    $cache = agentforge_session_get($session, 'agentforge_response_cache', []);
    if (!is_array($cache)) {
        $cache = [];
    }
    $cache[$key] = [
        'expires_at' => time() + $ttl,
        'response' => $response,
    ];
    if (count($cache) > 10) {
        uasort($cache, fn($a, $b) => (int)($a['expires_at'] ?? 0) <=> (int)($b['expires_at'] ?? 0));
        $cache = array_slice($cache, -10, null, true);
    }
    agentforge_session_set($session, 'agentforge_response_cache', $cache);
}

function agentforge_json_response(array $payload, int $status = 200): void
{
    http_response_code($status);
    echo json_encode($payload);
    exit;
}
