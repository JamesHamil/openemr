<?php

/**
 * Compatibility helpers for OpenEMR session/CSRF APIs across supported images.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

use OpenEMR\Common\Csrf\CsrfUtils;
use OpenEMR\Common\Session\SessionWrapperFactory;

function agentforge_openemr_session()
{
    $factory = SessionWrapperFactory::getInstance();

    if (method_exists($factory, 'getActiveSession')) {
        return $factory->getActiveSession();
    }

    if (method_exists($factory, 'getWrapper')) {
        return $factory->getWrapper();
    }

    return null;
}

function agentforge_session_get($session, string $key, $default = null)
{
    if (is_object($session) && method_exists($session, 'get')) {
        return $session->get($key, $default);
    }

    return $_SESSION[$key] ?? $default;
}

function agentforge_session_set($session, string $key, $value): void
{
    if (is_object($session) && method_exists($session, 'set')) {
        $session->set($key, $value);
        return;
    }

    $_SESSION[$key] = $value;
}

function agentforge_collect_csrf_token($session): string
{
    try {
        $method = new ReflectionMethod(CsrfUtils::class, 'collectCsrfToken');
        $parameters = $method->getParameters();

        if (($parameters[0]->getName() ?? '') === 'session') {
            return (string) CsrfUtils::collectCsrfToken($session);
        }

        return (string) CsrfUtils::collectCsrfToken();
    } catch (Throwable $e) {
        return '';
    }
}

function agentforge_verify_csrf_token(string $token, $session): bool
{
    try {
        $method = new ReflectionMethod(CsrfUtils::class, 'verifyCsrfToken');
        $parameters = $method->getParameters();

        if (($parameters[1]->getName() ?? '') === 'session') {
            return CsrfUtils::verifyCsrfToken($token, $session);
        }

        return CsrfUtils::verifyCsrfToken($token);
    } catch (Throwable $e) {
        return false;
    }
}
