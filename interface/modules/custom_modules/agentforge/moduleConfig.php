<?php

/**
 * AgentForge Clinical Co-Pilot module metadata.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

return [
    'name' => 'AgentForge Clinical Co-Pilot',
    'description' => 'Read-only, source-backed clinical co-pilot panel for hospitalist rounding workflows.',
    'version' => '0.1.0',
    'author' => 'AgentForge',
    'license' => 'GPL-3.0',
    'acl_category' => 'patients',
    'acl_section' => 'demo',
    'require' => [
        'openemr' => '>=7.0.0',
    ],
    'install' => [
        'sql' => 'sql/install.sql',
    ],
    'uninstall' => [
        'sql' => 'sql/uninstall.sql',
    ],
    'menu' => [
        [
            'label' => 'Clinical Co-Pilot',
            'menu_id' => 'patient',
            'acl' => ['patients', 'demo'],
            'url' => '/interface/modules/custom_modules/agentforge/public/index.php',
        ],
    ],
];
