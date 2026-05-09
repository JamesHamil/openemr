<?php

/**
 * AgentForge Clinical Co-Pilot patient panel.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

require_once(__DIR__ . "/../../../../globals.php");
require_once(__DIR__ . "/../src/AgentForgeOpenEmrCompat.php");

use OpenEMR\Common\Acl\AclMain;
use OpenEMR\Core\Header;

$session = agentforge_openemr_session();
$pid = (string)agentforge_session_get($session, 'pid', '');
$encounter = (string)agentforge_session_get($session, 'encounter', '');
$csrfToken = agentforge_collect_csrf_token($session);
$authorized = AclMain::aclCheckCore('patients', 'demo') || AclMain::aclCheckCore('patients', 'med') || AclMain::aclCheckCore('patients', 'notes');
?>
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title><?php echo xlt('Clinical Co-Pilot'); ?></title>
    <?php Header::setupHeader(['common']); ?>
    <style>
        .agentforge-shell {
            max-width: 980px;
            margin: 1rem auto;
        }
        .agentforge-panel {
            border: 1px solid var(--gray300, #dee2e6);
            border-radius: 6px;
            background: var(--white, #fff);
        }
        .agentforge-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            padding: 0.85rem 1rem;
            border-bottom: 1px solid var(--gray300, #dee2e6);
        }
        .agentforge-body {
            padding: 1rem;
        }
        .agentforge-status {
            font-size: 0.85rem;
            border-radius: 4px;
            padding: 0.25rem 0.5rem;
            background: var(--gray100, #f8f9fa);
            border: 1px solid var(--gray300, #dee2e6);
        }
        .agentforge-response {
            min-height: 180px;
            border: 1px solid var(--gray300, #dee2e6);
            border-radius: 4px;
            padding: 0.8rem;
            background: var(--gray100, #f8f9fa);
        }
        .agentforge-answer-summary {
            margin-bottom: 0.75rem;
            white-space: pre-wrap;
        }
        .agentforge-stream-progress {
            color: var(--gray700, #495057);
            display: grid;
            gap: 0.35rem;
        }
        .agentforge-stream-progress strong {
            color: var(--gray900, #212529);
        }
        .agentforge-section {
            margin: 0.75rem 0 0;
        }
        .agentforge-section h4 {
            font-size: 1rem;
            margin: 0 0 0.35rem;
        }
        .agentforge-section ul {
            margin-bottom: 0;
        }
        .agentforge-citation {
            color: var(--gray600, #6c757d);
            font-size: 0.85em;
        }
        .agentforge-meta {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 0.75rem;
            margin-top: 0.75rem;
        }
        .agentforge-meta-box {
            border: 1px solid var(--gray300, #dee2e6);
            border-radius: 4px;
            padding: 0.65rem;
            background: var(--white, #fff);
            max-height: 220px;
            overflow: auto;
        }
        .agentforge-source-meta {
            color: var(--gray600, #6c757d);
            display: block;
            font-size: 0.85em;
        }
        .agentforge-source-link {
            margin-left: 0.35rem;
        }
    </style>
</head>
<body class="body_top">
<main class="agentforge-shell">
    <div class="agentforge-panel">
        <div class="agentforge-header">
            <div>
                <h3 class="m-0"><?php echo xlt('Clinical Co-Pilot'); ?></h3>
                <div class="text-muted"><?php echo xlt('Read-only, source-backed chart brief for rounds.'); ?></div>
            </div>
            <span id="agentforgeStatus" class="agentforge-status"><?php echo xlt('Ready'); ?></span>
        </div>
        <div class="agentforge-body">
            <?php if (!$authorized) : ?>
                <div class="alert alert-danger"><?php echo xlt('You do not have permission to use Clinical Co-Pilot.'); ?></div>
            <?php elseif (empty($pid)) : ?>
                <div class="alert alert-warning"><?php echo xlt('Open a patient chart before using Clinical Co-Pilot.'); ?></div>
            <?php else : ?>
                <input type="hidden" id="agentforgeCsrf" value="<?php echo attr($csrfToken); ?>">
                <input type="hidden" id="agentforgePatientId" value="<?php echo attr($pid); ?>">
                <input type="hidden" id="agentforgeEncounterId" value="<?php echo attr($encounter); ?>">

                <div class="form-group">
                    <label for="agentforgeMessage"><?php echo xlt('Question'); ?></label>
                    <textarea id="agentforgeMessage" class="form-control" rows="3"><?php echo text('Give me a chart brief for rounds.'); ?></textarea>
                </div>
                <div class="mb-3">
                    <button type="button" id="agentforgeBrief" class="btn btn-primary">
                        <i class="fa fa-notes-medical"></i> <?php echo xlt('Generate Brief'); ?>
                    </button>
                </div>

                <div id="agentforgeAnswer" class="agentforge-response"><?php echo xlt('The verified response will appear here.'); ?></div>
                <div class="agentforge-meta">
                    <div class="agentforge-meta-box">
                        <strong><?php echo xlt('Sources'); ?></strong>
                        <ul id="agentforgeSources" class="mb-0"></ul>
                    </div>
                    <div class="agentforge-meta-box">
                        <strong><?php echo xlt('Warnings'); ?></strong>
                        <ul id="agentforgeWarnings" class="mb-0"></ul>
                    </div>
                    <div class="agentforge-meta-box">
                        <strong><?php echo xlt('Trace'); ?></strong>
                        <div id="agentforgeTrace" class="text-muted"></div>
                    </div>
                </div>
            <?php endif; ?>
        </div>
    </div>
</main>
<script>
    (function () {
        const briefButton = document.getElementById('agentforgeBrief');
        if (!briefButton) {
            return;
        }

        const status = document.getElementById('agentforgeStatus');
        const answer = document.getElementById('agentforgeAnswer');
        const sources = document.getElementById('agentforgeSources');
        const warnings = document.getElementById('agentforgeWarnings');
        const trace = document.getElementById('agentforgeTrace');

        function renderList(node, items, renderer) {
            node.innerHTML = '';
            if (!items || items.length === 0) {
                const li = document.createElement('li');
                li.textContent = 'None';
                node.appendChild(li);
                return;
            }
            items.forEach(function (item) {
                const li = document.createElement('li');
                li.textContent = renderer(item);
                node.appendChild(li);
            });
        }

        function groupBy(items, key) {
            return (items || []).reduce(function (groups, item) {
                const group = item[key] || 'other';
                groups[group] = groups[group] || [];
                groups[group].push(item);
                return groups;
            }, {});
        }

        function titleize(value) {
            return String(value || 'other').replace(/_/g, ' ').replace(/\b\w/g, function (letter) {
                return letter.toUpperCase();
            });
        }

        function renderAnswer(payload) {
            answer.innerHTML = '';
            const claimsById = {};
            (payload.claims || []).forEach(function (claim) {
                claimsById[claim.id] = claim;
            });

            if (payload.answer) {
                const summary = document.createElement('div');
                summary.className = 'agentforge-answer-summary';
                summary.textContent = payload.answer;
                answer.appendChild(summary);
            }

            const sections = payload.sections || [];
            if (sections.length === 0) {
                if (!payload.answer) {
                    answer.textContent = 'No response body returned.';
                }
                return;
            }

            sections.forEach(function (section) {
                const sectionNode = document.createElement('section');
                sectionNode.className = 'agentforge-section';
                const heading = document.createElement('h4');
                heading.textContent = section.title || titleize(section.id);
                sectionNode.appendChild(heading);

                const list = document.createElement('ul');
                (section.claim_ids || []).forEach(function (claimId) {
                    const claim = claimsById[claimId];
                    if (!claim) {
                        return;
                    }
                    const item = document.createElement('li');
                    item.appendChild(document.createTextNode(claim.text));
                    if (claim.source_ids && claim.source_ids.length) {
                        const cite = document.createElement('span');
                        cite.className = 'agentforge-citation';
                        cite.textContent = ' [' + claim.source_ids.join(', ') + ']';
                        item.appendChild(cite);
                    }
                    list.appendChild(item);
                });
                if (list.children.length > 0) {
                    sectionNode.appendChild(list);
                    answer.appendChild(sectionNode);
                }
            });
        }

        function renderSources(items) {
            sources.innerHTML = '';
            if (!items || items.length === 0) {
                const li = document.createElement('li');
                li.textContent = 'None';
                sources.appendChild(li);
                return;
            }

            const groups = (items || []).reduce(function (memo, source) {
                const group = sourceGroup(source);
                memo[group] = memo[group] || [];
                memo[group].push(source);
                return memo;
            }, {});
            ['Patient Chart', 'Extracted Documents', 'Guidelines'].forEach(function (type) {
                if (!groups[type] || !groups[type].length) {
                    return;
                }
                const groupItem = document.createElement('li');
                groupItem.textContent = type;
                const groupList = document.createElement('ul');
                groups[type].forEach(function (source) {
                    const sourceItem = document.createElement('li');
                    const label = document.createElement('span');
                    label.textContent = source.id + ': ' + source.extracted_value;
                    sourceItem.appendChild(label);
                    const documentUrl = documentSourceUrl(source);
                    if (documentUrl) {
                        const link = document.createElement('a');
                        link.className = 'agentforge-source-link';
                        link.href = documentUrl;
                        link.target = '_blank';
                        link.rel = 'noopener noreferrer';
                        link.textContent = 'open';
                        sourceItem.appendChild(link);
                    }
                    const meta = sourceMetadata(source);
                    if (meta) {
                        const metaNode = document.createElement('span');
                        metaNode.className = 'agentforge-source-meta';
                        metaNode.textContent = meta;
                        sourceItem.appendChild(metaNode);
                    }
                    groupList.appendChild(sourceItem);
                });
                groupItem.appendChild(groupList);
                sources.appendChild(groupItem);
            });
        }

        function sourceGroup(source) {
            if (!source) {
                return 'Patient Chart';
            }
            if (source.record_type === 'guideline' || (source.metadata || {}).source_kind === 'guideline') {
                return 'Guidelines';
            }
            if (source.record_type === 'document_fact' || (source.metadata || {}).source_kind === 'document_extraction') {
                return 'Extracted Documents';
            }
            return 'Patient Chart';
        }

        function parseCitation(source) {
            const raw = (source.metadata || {}).citation || '';
            if (!raw) {
                return {};
            }
            try {
                return JSON.parse(raw);
            } catch (error) {
                return {};
            }
        }

        function sourceMetadata(source) {
            const metadata = source.metadata || {};
            if (sourceGroup(source) === 'Guidelines') {
                return [metadata.title, metadata.section, metadata.citation_label].filter(Boolean).join(' | ');
            }
            if (sourceGroup(source) === 'Extracted Documents') {
                const citation = parseCitation(source);
                const parts = [
                    metadata.filename,
                    citation.page_or_section,
                    citation.field_or_chunk_id,
                    citation.quote_or_value ? '"' + citation.quote_or_value + '"' : ''
                ].filter(Boolean);
                return parts.join(' | ');
            }
            return source.field_path || '';
        }

        function documentSourceUrl(source) {
            const documentId = (source.metadata || {}).openemr_document_id || '';
            const patientId = document.getElementById('agentforgePatientId').value || '';
            if (!documentId || !patientId) {
                return '';
            }
            const webroot = <?php echo js_escape($GLOBALS['webroot'] ?? ''); ?>;
            return webroot + '/controller.php?document&view&patient_id=' +
                encodeURIComponent(patientId) + '&doc_id=' + encodeURIComponent(documentId);
        }

        function renderTrace(payload) {
            trace.innerHTML = '';
            const details = document.createElement('details');
            const summary = document.createElement('summary');
            summary.textContent = 'Debug trace';
            const body = document.createElement('div');
            body.textContent = payload.trace_id || '';
            details.appendChild(summary);
            details.appendChild(body);
            if (payload.debug_trace) {
                const debug = document.createElement('pre');
                debug.textContent = JSON.stringify(payload.debug_trace, null, 2);
                details.appendChild(debug);
            }
            trace.appendChild(details);
        }

        function renderStreamProgress(message, elapsed) {
            answer.innerHTML = '';
            const node = document.createElement('div');
            node.className = 'agentforge-stream-progress';
            const title = document.createElement('strong');
            title.textContent = message;
            const detail = document.createElement('div');
            detail.className = 'text-muted';
            detail.textContent = 'Waiting for the verified, source-backed response' + (elapsed ? ' (' + elapsed + 's)' : '') + '.';
            node.appendChild(title);
            node.appendChild(detail);
            answer.appendChild(node);
        }

        function send(message) {
            if (top && typeof top.restoreSession === 'function') {
                top.restoreSession();
            }
            let elapsed = 0;
            let currentPhase = 'Starting request';
            status.textContent = currentPhase + ' 0s';
            renderStreamProgress(currentPhase, elapsed);
            briefButton.disabled = true;
            const timer = window.setInterval(function () {
                elapsed += 1;
                status.textContent = currentPhase + ' ' + elapsed + 's';
            }, 1000);
            const data = new URLSearchParams();
            data.set('csrf_token_form', document.getElementById('agentforgeCsrf').value);
            data.set('patient_id', document.getElementById('agentforgePatientId').value);
            data.set('encounter_id', document.getElementById('agentforgeEncounterId').value);
            data.set('conversation_id', 'rounding-' + document.getElementById('agentforgePatientId').value);
            data.set('message', message);
            data.set('stream', '1');

            function updatePhase(message) {
                currentPhase = message || currentPhase;
                status.textContent = currentPhase + ' ' + elapsed + 's';
                renderStreamProgress(currentPhase, elapsed);
            }

            function applyPayload(payload) {
                status.textContent = payload.verification_status || 'failed';
                renderAnswer(payload);
                renderSources(payload.sources || []);
                renderList(warnings, payload.warnings || [], function (warning) {
                    return warning.code + ': ' + warning.message;
                });
                renderTrace(payload);
            }

            function handleStreamLine(line) {
                if (!line.trim()) {
                    return;
                }
                let event = {};
                try {
                    event = JSON.parse(line);
                } catch (error) {
                    return;
                }
                if (event.schema_version === 'agentforge.response.v1') {
                    applyPayload(event);
                    return;
                }
                const payload = event.payload || {};
                if (event.event === 'progress') {
                    updatePhase(payload.message || currentPhase);
                    return;
                }
                if (event.event === 'final' || event.event === 'error') {
                    applyPayload(payload);
                }
            }

            fetch('chat.php', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: data.toString()
            }).then(async function (response) {
                const contentType = response.headers.get('Content-Type') || '';
                if (!response.body || contentType.indexOf('application/x-ndjson') === -1) {
                    applyPayload(await response.json());
                    return;
                }
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';
                while (true) {
                    const chunk = await reader.read();
                    if (chunk.value) {
                        buffer += decoder.decode(chunk.value, {stream: !chunk.done});
                        const lines = buffer.split('\n');
                        buffer = lines.pop() || '';
                        lines.forEach(handleStreamLine);
                    }
                    if (chunk.done) {
                        break;
                    }
                }
                if (buffer.trim()) {
                    handleStreamLine(buffer);
                }
            }).catch(function () {
                status.textContent = 'failed';
                answer.textContent = 'Clinical Co-Pilot request failed before a verified response was returned.';
            }).finally(function () {
                window.clearInterval(timer);
                briefButton.disabled = false;
            });
        }

        function messageInputValue() {
            const value = document.getElementById('agentforgeMessage').value || '';
            return value.trim();
        }

        briefButton.addEventListener('click', function () {
            const message = messageInputValue() || 'Give me a chart brief for rounds.';
            send(message);
        });
    })();
</script>
</body>
</html>
