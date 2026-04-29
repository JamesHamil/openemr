<?php

use OpenEMR\Core\AbstractModuleActionListener;

class ModuleManagerListener extends AbstractModuleActionListener
{
    public function __construct()
    {
        parent::__construct();
    }

    public function moduleManagerAction($methodName, $modId, string $currentActionStatus = 'Success'): string
    {
        if (method_exists(self::class, $methodName)) {
            return self::$methodName($modId, $currentActionStatus);
        }

        return $currentActionStatus;
    }

    public static function getModuleNamespace(): string
    {
        return 'OpenEMR\\Modules\\AgentForge\\';
    }

    public static function initListenerSelf(): ModuleManagerListener
    {
        return new self();
    }

    private function install($modId, $currentActionStatus): mixed
    {
        self::setModuleActiveState($modId, 0, 1);
        return $currentActionStatus;
    }

    private function enable($modId, $currentActionStatus): mixed
    {
        self::setModuleActiveState($modId, 1, 0);
        return $currentActionStatus;
    }

    private function disable($modId, $currentActionStatus): mixed
    {
        self::setModuleActiveState($modId, 0, 1);
        return $currentActionStatus;
    }
}
