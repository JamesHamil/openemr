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

function agentforge_copilot_asset_url(string $asset): string
{
    return (string)($GLOBALS['webroot'] ?? '')
        . "/interface/modules/custom_modules/agentforge/public/patient-dashboard/assets/"
        . rawurlencode($asset)
        . "?v=" . rawurlencode((string)($GLOBALS['v_js_includes'] ?? 'agentforge'));
}

$webroot = (string)($GLOBALS['webroot'] ?? '');
$config = [
    'authorized' => (bool)$authorized,
    'patientId' => $pid,
    'encounterId' => $encounter,
    'csrfToken' => $csrfToken,
    'chatUrl' => 'chat.php',
    'documentBaseUrl' => $webroot . '/controller.php',
];
$encodedConfig = json_encode(
    $config,
    JSON_HEX_TAG | JSON_HEX_APOS | JSON_HEX_AMP | JSON_HEX_QUOT | JSON_INVALID_UTF8_SUBSTITUTE
);
?>
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title><?php echo xlt('Clinical Co-Pilot'); ?></title>
    <?php Header::setupHeader(['common']); ?>
    <link rel="stylesheet" href="<?php echo attr(agentforge_copilot_asset_url('patient-dashboard.css')); ?>" />
</head>
<body class="body_top">
<div id="agentforge-copilot-root"></div>
<script>
window.__AGENTFORGE_COPILOT__ = <?php echo $encodedConfig ?: '{}'; ?>;
</script>
<script type="module" src="<?php echo attr(agentforge_copilot_asset_url('patient-dashboard.js')); ?>"></script>
</body>
</html>
