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

            const groups = groupBy(items, 'record_type');
            Object.keys(groups).sort().forEach(function (type) {
                const groupItem = document.createElement('li');
                groupItem.textContent = titleize(type);
                const groupList = document.createElement('ul');
                groups[type].forEach(function (source) {
                    const sourceItem = document.createElement('li');
                    sourceItem.textContent = source.id + ': ' + source.extracted_value;
                    groupList.appendChild(sourceItem);
                });
                groupItem.appendChild(groupList);
                sources.appendChild(groupItem);
            });
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
            trace.appendChild(details);
        }

        function send(message) {
            top.restoreSession();
            let elapsed = 0;
            status.textContent = 'Generating... 0s';
            briefButton.disabled = true;
            askButton.disabled = true;
            const timer = window.setInterval(function () {
                elapsed += 1;
                status.textContent = 'Generating... ' + elapsed + 's';
            }, 1000);
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
                renderAnswer(payload);
                renderSources(payload.sources || []);
                renderList(warnings, payload.warnings || [], function (warning) {
                    return warning.code + ': ' + warning.message;
                });
                renderTrace(payload);
            }).catch(function () {
                status.textContent = 'failed';
                answer.textContent = 'Clinical Co-Pilot request failed before a verified response was returned.';
            }).finally(function () {
                window.clearInterval(timer);
                briefButton.disabled = false;
                askButton.disabled = false;
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
        askButton.addEventListener('click', function () {
            const message = messageInputValue() || 'Give me a chart brief for rounds.';
            send(message);
        });
    })();
</script>
</body>
</html>
