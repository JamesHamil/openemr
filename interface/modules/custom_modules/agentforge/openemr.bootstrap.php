<?php

/**
 * AgentForge Clinical Co-Pilot module bootstrap.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

use OpenEMR\Core\ModulesClassLoader;
use OpenEMR\Menu\MenuEvent;
use OpenEMR\Menu\PatientMenuEvent;
use Symfony\Component\EventDispatcher\EventDispatcherInterface;

/**
 * @var ModulesClassLoader $classLoader
 */
$classLoader->registerNamespaceIfNotExists('OpenEMR\\Modules\\AgentForge\\', __DIR__ . DIRECTORY_SEPARATOR . 'src');

function oe_module_agentforge_add_main_menu_item(MenuEvent $event): MenuEvent
{
    $menu = $event->getMenu();

    $menuItem = new stdClass();
    $menuItem->requirement = 0;
    $menuItem->target = 'mod';
    $menuItem->menu_id = 'agentforge0';
    $menuItem->label = xlt("Clinical Co-Pilot");
    $menuItem->url = "/interface/modules/custom_modules/agentforge/public/index.php";
    $menuItem->on_click = 'top.restoreSession()';
    $menuItem->pid = 'false';
    $menuItem->children = [];
    $menuItem->acl_req = ["patients", "demo"];
    $menuItem->global_req = [];

    foreach ($menu as $item) {
        if ($item->menu_id === 'patimg' || ($item->label ?? '') === 'Patient') {
            $item->children[] = $menuItem;
            break;
        }
    }

    $event->setMenu($menu);
    return $event;
}

function oe_module_agentforge_add_patient_menu_item(PatientMenuEvent $event): PatientMenuEvent
{
    $existingMenu = $event->getMenu();
    $webroot = $GLOBALS['webroot'] ?? '';

    $menuItem = new stdClass();
    $menuItem->label = "Co-Pilot";
    $menuItem->url = $webroot . "/interface/modules/custom_modules/agentforge/public/index.php";
    $menuItem->menu_id = "agentforge_patient";
    $menuItem->target = "main";
    $menuItem->on_click = "top.restoreSession()";
    $menuItem->pid = "false";
    $menuItem->children = [];
    $menuItem->requirement = 0;

    $existingMenu[] = $menuItem;
    $event->setMenu($existingMenu);
    return $event;
}

/**
 * @var EventDispatcherInterface $eventDispatcher
 */
$eventDispatcher->addListener(MenuEvent::MENU_UPDATE, 'oe_module_agentforge_add_main_menu_item');
$eventDispatcher->addListener(PatientMenuEvent::MENU_UPDATE, 'oe_module_agentforge_add_patient_menu_item');
