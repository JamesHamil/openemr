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
            white-space: pre-wrap;
            border: 1px solid var(--gray300, #dee2e6);
            border-radius: 4px;
            padding: 0.8rem;
            background: var(--gray100, #f8f9fa);
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
                    <button type="button" id="agentforgeAsk" class="btn btn-secondary">
                        <i class="fa fa-comment-medical"></i> <?php echo xlt('Ask Follow-Up'); ?>
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
        const askButton = document.getElementById('agentforgeAsk');
        if (!briefButton || !askButton) {
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

        function send(message) {
            top.restoreSession();
            status.textContent = 'Working';
            const data = new URLSearchParams();
            data.set('csrf_token_form', document.getElementById('agentforgeCsrf').value);
            data.set('patient_id', document.getElementById('agentforgePatientId').value);
            data.set('encounter_id', document.getElementById('agentforgeEncounterId').value);
            data.set('conversation_id', 'rounding-' + document.getElementById('agentforgePatientId').value);
            data.set('message', message);

            fetch('chat.php', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: data.toString()
            }).then(function (response) {
                return response.json();
            }).then(function (payload) {
                status.textContent = payload.verification_status || 'failed';
                answer.textContent = payload.answer || 'No response body returned.';
                renderList(sources, payload.sources || [], function (source) {
                    return source.id + ' - ' + source.record_type + ': ' + source.extracted_value;
                });
                renderList(warnings, payload.warnings || [], function (warning) {
                    return warning.code + ': ' + warning.message;
                });
                trace.textContent = payload.trace_id || '';
            }).catch(function () {
                status.textContent = 'failed';
                answer.textContent = 'Clinical Co-Pilot request failed before a verified response was returned.';
            });
        }

        briefButton.addEventListener('click', function () {
            send('Give me a chart brief for rounds.');
        });
        askButton.addEventListener('click', function () {
            send(document.getElementById('agentforgeMessage').value);
        });
    })();
</script>
</body>
</html>
