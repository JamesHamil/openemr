<?php

namespace OpenEMR\Modules\AgentForge;

class AgentForgeSidecarClient
{
    public function send(array $payload): array
    {
        $sidecarUrl = rtrim((string)getenv('AGENTFORGE_SIDECAR_URL'), '/');
        if ($sidecarUrl === '') {
            return $this->fallbackResponse('AgentForge sidecar URL is not configured.');
        }

        $secret = (string)(getenv('AGENTFORGE_SIGNING_SECRET') ?: 'dev-agentforge-signing-secret');
        $body = $this->canonicalJson($payload);
        $signature = hash_hmac('sha256', $body, $secret);

        $context = stream_context_create([
            'http' => [
                'method' => 'POST',
                'header' => [
                    'Content-Type: application/json',
                    'X-AgentForge-Signature: ' . $signature,
                ],
                'content' => $body,
                'timeout' => $this->timeoutSeconds(),
                'ignore_errors' => true,
            ],
        ]);

        $raw = @file_get_contents($sidecarUrl . '/v1/chat', false, $context);
        if ($raw === false || $raw === '') {
            return $this->fallbackResponse('AgentForge sidecar did not return a response.');
        }

        $decoded = json_decode($raw, true);
        if (!is_array($decoded)) {
            return $this->fallbackResponse('AgentForge sidecar returned malformed JSON.');
        }

        return $decoded;
    }

    private function fallbackResponse(string $message): array
    {
        return [
            'schema_version' => 'agentforge.response.v1',
            'answer' => 'Clinical Co-Pilot is unavailable. ' . $message,
            'sections' => [],
            'claims' => [],
            'sources' => [],
            'warnings' => [
                [
                    'code' => 'sidecar_unavailable',
                    'message' => $message,
                ],
            ],
            'blocked_claims' => [],
            'verification_status' => 'failed',
            'trace_id' => 'local-unavailable-' . bin2hex(random_bytes(4)),
        ];
    }

    private function canonicalJson(array $payload): string
    {
        $this->sortRecursive($payload);
        return json_encode($payload, JSON_UNESCAPED_SLASHES);
    }

    private function timeoutSeconds(): int
    {
        $configured = (int)(getenv('AGENTFORGE_SIDECAR_TIMEOUT_SECONDS') ?: 75);
        return max(15, min($configured, 120));
    }

    private function sortRecursive(array &$value): void
    {
        foreach ($value as &$child) {
            if (is_array($child)) {
                $this->sortRecursive($child);
            }
        }
        if (!$this->isList($value)) {
            ksort($value);
        }
    }

    private function isList(array $value): bool
    {
        return array_keys($value) === range(0, count($value) - 1);
    }
}
