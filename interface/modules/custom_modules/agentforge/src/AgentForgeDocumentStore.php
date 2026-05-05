<?php

namespace OpenEMR\Modules\AgentForge;

class AgentForgeDocumentStore
{
    public function ensureTables(): void
    {
        sqlStatement(
            "CREATE TABLE IF NOT EXISTS `agentforge_documents` (" .
            "`id` BIGINT NOT NULL AUTO_INCREMENT," .
            "`pid` BIGINT NOT NULL," .
            "`encounter_id` BIGINT DEFAULT NULL," .
            "`openemr_document_id` BIGINT DEFAULT NULL," .
            "`document_type` VARCHAR(32) NOT NULL," .
            "`original_filename` VARCHAR(255) NOT NULL," .
            "`mime_type` VARCHAR(120) NOT NULL," .
            "`file_hash` CHAR(64) NOT NULL," .
            "`extraction_status` VARCHAR(32) NOT NULL DEFAULT 'pending'," .
            "`extraction_trace_id` VARCHAR(120) DEFAULT NULL," .
            "`extraction_summary` TEXT DEFAULT NULL," .
            "`created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP," .
            "`updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP," .
            "PRIMARY KEY (`id`), KEY `idx_agentforge_documents_pid` (`pid`), " .
            "KEY `idx_agentforge_documents_openemr_document_id` (`openemr_document_id`), " .
            "KEY `idx_agentforge_documents_type_status` (`document_type`, `extraction_status`)" .
            ") ENGINE=InnoDB COMMENT='AgentForge OpenEMR document extraction tracking'"
        );
        sqlStatement(
            "CREATE TABLE IF NOT EXISTS `agentforge_extracted_facts` (" .
            "`id` BIGINT NOT NULL AUTO_INCREMENT," .
            "`agentforge_document_id` BIGINT NOT NULL," .
            "`pid` BIGINT NOT NULL," .
            "`openemr_document_id` BIGINT DEFAULT NULL," .
            "`fact_type` VARCHAR(64) NOT NULL," .
            "`label` VARCHAR(160) NOT NULL," .
            "`value` TEXT NOT NULL," .
            "`unit` VARCHAR(64) DEFAULT ''," .
            "`reference_range` VARCHAR(120) DEFAULT ''," .
            "`abnormal_flag` VARCHAR(64) DEFAULT ''," .
            "`recorded_at` VARCHAR(64) DEFAULT ''," .
            "`confidence` DECIMAL(5,4) DEFAULT 0.0000," .
            "`citation_json` TEXT NOT NULL," .
            "`created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP," .
            "PRIMARY KEY (`id`), KEY `idx_agentforge_facts_document` (`agentforge_document_id`), " .
            "KEY `idx_agentforge_facts_pid` (`pid`), KEY `idx_agentforge_facts_type` (`fact_type`)" .
            ") ENGINE=InnoDB COMMENT='AgentForge source-cited extracted facts'"
        );
    }

    public function createDocumentRecord(
        string $pid,
        string $encounterId,
        ?int $openEmrDocumentId,
        string $documentType,
        string $filename,
        string $mimeType,
        string $fileHash
    ): int {
        $this->ensureTables();
        if ($openEmrDocumentId !== null) {
            $existing = sqlQuery(
                "SELECT id FROM agentforge_documents WHERE pid = ? AND openemr_document_id = ? AND document_type = ? " .
                "ORDER BY id DESC LIMIT 1",
                [(int)$pid, $openEmrDocumentId, $documentType]
            );
            if (!empty($existing['id'])) {
                sqlStatement(
                    "UPDATE agentforge_documents SET encounter_id = ?, original_filename = ?, mime_type = ?, " .
                    "file_hash = ?, extraction_status = 'pending', extraction_trace_id = NULL, extraction_summary = NULL " .
                    "WHERE id = ?",
                    [
                        $encounterId !== '' ? (int)$encounterId : null,
                        $filename,
                        $mimeType,
                        $fileHash,
                        (int)$existing['id'],
                    ]
                );
                return (int)$existing['id'];
            }
        }

        return (int)sqlInsert(
            "INSERT INTO agentforge_documents " .
            "(pid, encounter_id, openemr_document_id, document_type, original_filename, mime_type, file_hash, extraction_status) " .
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')",
            [
                (int)$pid,
                $encounterId !== '' ? (int)$encounterId : null,
                $openEmrDocumentId,
                $documentType,
                $filename,
                $mimeType,
                $fileHash,
            ]
        );
    }

    public function replaceFacts(int $agentforgeDocumentId, string $pid, ?int $openEmrDocumentId, array $extraction): void
    {
        $this->ensureTables();
        sqlStatement("DELETE FROM agentforge_extracted_facts WHERE agentforge_document_id = ?", [$agentforgeDocumentId]);
        foreach (($extraction['extracted_facts'] ?? []) as $fact) {
            $citation = $fact['citation'] ?? [];
            sqlStatement(
                "INSERT INTO agentforge_extracted_facts " .
                "(agentforge_document_id, pid, openemr_document_id, fact_type, label, value, unit, reference_range, abnormal_flag, recorded_at, confidence, citation_json) " .
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    $agentforgeDocumentId,
                    (int)$pid,
                    $openEmrDocumentId,
                    (string)($fact['fact_type'] ?? 'document_fact'),
                    substr((string)($fact['label'] ?? 'Document fact'), 0, 160),
                    (string)($fact['value'] ?? ''),
                    substr((string)($fact['unit'] ?? ''), 0, 64),
                    substr((string)($fact['reference_range'] ?? ''), 0, 120),
                    substr((string)($fact['abnormal_flag'] ?? ''), 0, 64),
                    substr((string)($fact['recorded_at'] ?? ''), 0, 64),
                    max(0, min((float)($fact['confidence'] ?? 0), 1)),
                    json_encode($citation, JSON_UNESCAPED_SLASHES),
                ]
            );
        }

        sqlStatement(
            "UPDATE agentforge_documents SET extraction_status = ?, extraction_trace_id = ?, extraction_summary = ? WHERE id = ?",
            [
                (string)($extraction['extraction_status'] ?? 'partial'),
                (string)($extraction['trace_id'] ?? ''),
                json_encode([
                    'warnings' => $extraction['warnings'] ?? [],
                    'worker_handoffs' => $extraction['worker_handoffs'] ?? [],
                    'fact_count' => count($extraction['extracted_facts'] ?? []),
                ], JSON_UNESCAPED_SLASHES),
                $agentforgeDocumentId,
            ]
        );
    }

    public function recentFactSources(string $pid, int $limit = 12): array
    {
        $this->ensureTables();
        $result = sqlStatement(
            "SELECT f.id, f.fact_type, f.label, f.value, f.unit, f.reference_range, f.abnormal_flag, f.recorded_at, " .
            "f.confidence, f.citation_json, d.document_type, d.original_filename, d.openemr_document_id, d.created_at " .
            "FROM agentforge_extracted_facts f " .
            "JOIN agentforge_documents d ON d.id = f.agentforge_document_id " .
            "WHERE f.pid = ? " .
            "ORDER BY f.created_at DESC, f.id DESC LIMIT ?",
            [(int)$pid, $limit]
        );
        $sources = [];
        while ($row = sqlFetchArray($result)) {
            $valueParts = [
                (string)$row['label'],
                (string)$row['value'],
            ];
            if (!empty($row['unit'])) {
                $valueParts[] = 'unit ' . (string)$row['unit'];
            }
            if (!empty($row['reference_range'])) {
                $valueParts[] = 'range ' . (string)$row['reference_range'];
            }
            if (!empty($row['abnormal_flag'])) {
                $valueParts[] = 'abnormal ' . (string)$row['abnormal_flag'];
            }
            $citation = json_decode((string)$row['citation_json'], true);
            $sources[] = [
                'id' => 'document-fact-' . (string)$row['id'],
                'record_type' => 'document_fact',
                'recorded_at' => (string)($row['recorded_at'] ?: $row['created_at']),
                'field_path' => 'agentforge_extracted_facts.' . (string)$row['fact_type'],
                'value' => implode('; ', array_filter($valueParts)),
                'metadata' => [
                    'source_kind' => 'document_extraction',
                    'document_type' => (string)$row['document_type'],
                    'openemr_document_id' => (string)$row['openemr_document_id'],
                    'filename' => (string)$row['original_filename'],
                    'confidence' => (string)$row['confidence'],
                    'citation' => json_encode(is_array($citation) ? $citation : [], JSON_UNESCAPED_SLASHES),
                ],
            ];
        }
        return $sources;
    }

    public function recentDocuments(string $pid, int $limit = 5): array
    {
        $this->ensureTables();
        $result = sqlStatement(
            "SELECT id, openemr_document_id, document_type, original_filename, extraction_status, extraction_trace_id, created_at " .
            "FROM agentforge_documents WHERE pid = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            [(int)$pid, $limit]
        );
        $documents = [];
        while ($row = sqlFetchArray($result)) {
            $documents[] = $row;
        }
        return $documents;
    }
}
