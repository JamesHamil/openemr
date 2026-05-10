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
        sqlStatement(
            "CREATE TABLE IF NOT EXISTS `agentforge_chart_writebacks` (" .
            "`id` BIGINT NOT NULL AUTO_INCREMENT," .
            "`pid` BIGINT NOT NULL," .
            "`agentforge_document_id` BIGINT NOT NULL," .
            "`openemr_document_id` BIGINT DEFAULT NULL," .
            "`agentforge_fact_id` BIGINT DEFAULT NULL," .
            "`target_table` VARCHAR(64) NOT NULL," .
            "`target_field` VARCHAR(120) NOT NULL DEFAULT ''," .
            "`target_record_id` VARCHAR(120) NOT NULL DEFAULT ''," .
            "`old_value` TEXT DEFAULT NULL," .
            "`new_value` TEXT DEFAULT NULL," .
            "`action` VARCHAR(32) NOT NULL," .
            "`status` VARCHAR(32) NOT NULL," .
            "`trace_id` VARCHAR(120) DEFAULT NULL," .
            "`message` TEXT DEFAULT NULL," .
            "`created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP," .
            "PRIMARY KEY (`id`), KEY `idx_agentforge_writebacks_pid` (`pid`), " .
            "KEY `idx_agentforge_writebacks_document` (`agentforge_document_id`), " .
            "KEY `idx_agentforge_writebacks_fact` (`agentforge_fact_id`)" .
            ") ENGINE=InnoDB COMMENT='AgentForge chart writeback audit log'"
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
            if (is_array($fact)) {
                $this->insertFact($agentforgeDocumentId, $pid, $openEmrDocumentId, $fact);
            }
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

    public function loadDocumentExtraction(string $pid, int $openEmrDocumentId, string $documentType = ''): ?array
    {
        $this->ensureTables();
        $params = [(int)$pid, $openEmrDocumentId];
        $typeClause = '';
        if ($documentType !== '') {
            $typeClause = " AND document_type = ?";
            $params[] = $documentType;
        }

        $document = sqlQuery(
            "SELECT id, openemr_document_id, document_type, original_filename, mime_type, file_hash, " .
            "extraction_status, extraction_trace_id, extraction_summary " .
            "FROM agentforge_documents WHERE pid = ? AND openemr_document_id = ?" . $typeClause . " " .
            "ORDER BY updated_at DESC, id DESC LIMIT 1",
            $params
        );
        if (empty($document['id'])) {
            return null;
        }

        $facts = [];
        $result = sqlStatement(
            "SELECT id, fact_type, label, value, unit, reference_range, abnormal_flag, recorded_at, confidence, citation_json " .
            "FROM agentforge_extracted_facts WHERE agentforge_document_id = ? ORDER BY id ASC",
            [(int)$document['id']]
        );
        while ($row = sqlFetchArray($result)) {
            $factIndex = count($facts);
            $citation = json_decode((string)$row['citation_json'], true);
            if (is_array($citation)) {
                if (
                    (string)$document['document_type'] === 'intake_form' &&
                    strpos(strtolower((string)$document['mime_type']), 'image/') === 0 &&
                    $this->isSuspiciousIntakeImageBox($citation, (string)$row['fact_type'])
                ) {
                    unset($citation['bounding_box'], $citation['bounding_box_source']);
                }
                $fallbackBox = $this->imageFallbackBoundingBox(
                    (string)$document['document_type'],
                    (string)$document['mime_type'],
                    $citation,
                    (string)$row['fact_type'],
                    $factIndex
                );
                if ($fallbackBox !== null) {
                    $citation['bounding_box'] = $fallbackBox;
                    $citation['bounding_box_source'] = 'agentforge-fallback';
                }
            }
            $facts[] = [
                'id' => (string)$row['id'],
                'fact_type' => (string)$row['fact_type'],
                'label' => (string)$row['label'],
                'value' => (string)$row['value'],
                'unit' => (string)$row['unit'],
                'reference_range' => (string)$row['reference_range'],
                'abnormal_flag' => (string)$row['abnormal_flag'],
                'recorded_at' => (string)$row['recorded_at'],
                'confidence' => max(0, min((float)$row['confidence'], 1)),
                'citation' => is_array($citation) ? $citation : [],
            ];
        }

        $summary = json_decode((string)($document['extraction_summary'] ?? ''), true);
        if (!is_array($summary)) {
            $summary = [];
        }

        return [
            'document' => [
                'agentforge_document_id' => (int)$document['id'],
                'openemr_document_id' => (int)$document['openemr_document_id'],
                'document_type' => (string)$document['document_type'],
                'filename' => (string)$document['original_filename'],
                'mime_type' => (string)$document['mime_type'],
                'file_hash' => (string)$document['file_hash'],
            ],
            'extraction' => [
                'schema_version' => 'agentforge.document_extract.response.v1',
                'document_type' => (string)$document['document_type'],
                'extraction_status' => (string)($document['extraction_status'] ?: 'partial'),
                'extracted_facts' => $facts,
                'warnings' => is_array($summary['warnings'] ?? null) ? $summary['warnings'] : [],
                'worker_handoffs' => is_array($summary['worker_handoffs'] ?? null) ? $summary['worker_handoffs'] : [],
                'trace_id' => (string)($document['extraction_trace_id'] ?: ''),
            ],
        ];
    }

    public function saveEditedFacts(
        int $agentforgeDocumentId,
        string $pid,
        ?int $openEmrDocumentId,
        string $documentType,
        array $facts,
        string $traceId
    ): void {
        $cleanFacts = [];
        foreach ($facts as $index => $fact) {
            if (is_array($fact)) {
                $cleanFacts[] = $this->cleanFact($fact, $documentType, $openEmrDocumentId, $index);
            }
        }

        $this->replaceFacts($agentforgeDocumentId, $pid, $openEmrDocumentId, [
            'schema_version' => 'agentforge.document_extract.response.v1',
            'document_type' => $documentType,
            'extraction_status' => count($cleanFacts) > 0 ? 'success' : 'partial',
            'extracted_facts' => $cleanFacts,
            'warnings' => [],
            'worker_handoffs' => [],
            'trace_id' => $traceId,
        ]);
    }

    private function insertFact(int $agentforgeDocumentId, string $pid, ?int $openEmrDocumentId, array $fact): void
    {
        $citation = is_array($fact['citation'] ?? null) ? $fact['citation'] : [];
        sqlStatement(
            "INSERT INTO agentforge_extracted_facts " .
            "(agentforge_document_id, pid, openemr_document_id, fact_type, label, value, unit, reference_range, abnormal_flag, recorded_at, confidence, citation_json) " .
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                $agentforgeDocumentId,
                (int)$pid,
                $openEmrDocumentId,
                substr((string)($fact['fact_type'] ?? 'document_fact'), 0, 64),
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

    private function cleanFact(array $fact, string $documentType, ?int $openEmrDocumentId, int $index): array
    {
        $factType = trim((string)($fact['fact_type'] ?? ''));
        if ($factType === '') {
            $factType = 'document_fact';
        }

        $label = trim((string)($fact['label'] ?? ''));
        if ($label === '') {
            $label = 'Document fact';
        }

        return [
            'fact_type' => substr($factType, 0, 64),
            'label' => substr($label, 0, 160),
            'value' => trim((string)($fact['value'] ?? '')),
            'unit' => substr(trim((string)($fact['unit'] ?? '')), 0, 64),
            'reference_range' => substr(trim((string)($fact['reference_range'] ?? '')), 0, 120),
            'abnormal_flag' => substr(trim((string)($fact['abnormal_flag'] ?? '')), 0, 64),
            'recorded_at' => substr(trim((string)($fact['recorded_at'] ?? '')), 0, 64),
            'confidence' => max(0, min((float)($fact['confidence'] ?? 0), 1)),
            'citation' => $this->cleanCitation(
                is_array($fact['citation'] ?? null) ? $fact['citation'] : [],
                $documentType,
                $openEmrDocumentId,
                $factType,
                $index
            ),
        ];
    }

    private function cleanCitation(array $citation, string $documentType, ?int $openEmrDocumentId, string $factType, int $index): array
    {
        $sourceType = trim((string)($citation['source_type'] ?? ''));
        if ($sourceType === '') {
            $sourceType = $documentType;
        }
        $sourceId = trim((string)($citation['source_id'] ?? ''));
        if ($sourceId === '') {
            $sourceId = 'openemr-document-' . (string)$openEmrDocumentId;
        }
        $fieldOrChunk = trim((string)($citation['field_or_chunk_id'] ?? ''));
        if ($fieldOrChunk === '') {
            $fieldOrChunk = $factType . '-' . ($index + 1);
        }

        $clean = [
            'source_type' => substr($sourceType, 0, 64),
            'source_id' => substr($sourceId, 0, 120),
            'page_or_section' => substr(trim((string)($citation['page_or_section'] ?? '')), 0, 160),
            'field_or_chunk_id' => substr($fieldOrChunk, 0, 160),
            'quote_or_value' => substr(trim((string)($citation['quote_or_value'] ?? '')), 0, 1000),
        ];

        $box = $this->normalizeBoundingBox(is_array($citation['bounding_box'] ?? null) ? $citation['bounding_box'] : null);
        if ($box !== null) {
            $clean['bounding_box'] = $box;
        }

        return $clean;
    }

    private function normalizeBoundingBox(?array $box): ?array
    {
        if ($box === null) {
            return null;
        }

        $normalized = [];
        foreach (['x', 'y', 'width', 'height'] as $key) {
            if (!isset($box[$key]) || !is_numeric($box[$key])) {
                return null;
            }
            $normalized[$key] = max(0, min((float)$box[$key], 1));
        }

        $normalized['width'] = min($normalized['width'], 1 - $normalized['x']);
        $normalized['height'] = min($normalized['height'], 1 - $normalized['y']);
        if ($normalized['width'] <= 0 || $normalized['height'] <= 0) {
            return null;
        }

        if (isset($box['page']) && is_numeric($box['page']) && (int)$box['page'] > 0) {
            $normalized['page'] = (int)$box['page'];
        }

        return $normalized;
    }

    private function imageFallbackBoundingBox(
        string $documentType,
        string $mimeType,
        array $citation,
        string $factType,
        int $index
    ): ?array {
        if (strpos(strtolower($mimeType), 'image/') !== 0) {
            return null;
        }
        if (isset($citation['bounding_box']) && is_array($citation['bounding_box'])) {
            return null;
        }

        if ($documentType === 'medication_list' && in_array($factType, ['medication', 'medication_document'], true)) {
            return [
                'x' => 0.06,
                'y' => min(0.9, 0.17 + ($index * 0.046)),
                'width' => 0.88,
                'height' => 0.042,
                'page' => 1,
                'bounding_box_source' => 'agentforge-fallback',
            ];
        }

        return null;
    }

    private function isSuspiciousIntakeImageBox(array $citation, string $factType): bool
    {
        $box = is_array($citation['bounding_box'] ?? null) ? $citation['bounding_box'] : null;
        if ($box === null || !isset($box['y']) || !is_numeric($box['y'])) {
            return false;
        }

        $fieldKey = strtolower(
            (string)($citation['field_or_chunk_id'] ?? '') . ' ' .
            $factType . ' ' .
            (string)($citation['quote_or_value'] ?? '')
        );
        $topDemographicTerms = [
            'name',
            'dob',
            'date of birth',
            'birth',
            'mrn',
            'sex',
            'gender',
            'race',
            'ethnicity',
            'email',
        ];
        foreach ($topDemographicTerms as $term) {
            if (strpos($fieldKey, $term) !== false) {
                return (float)$box['y'] > 0.38;
            }
        }

        return false;
    }

    public function recentFactSources(string $pid, ?int $limit = null, string $message = ''): array
    {
        $this->ensureTables();
        $orderBy = "f.created_at DESC, f.id DESC";
        if ($this->isLabPrompt($message)) {
            $labTerms = "hemoglobin|hematocrit|leukocyte|platelet|erythrocyte|mcv|neutrophil|lymphocyte|metamyelocyte|promyelocyte|blast|monocyte|eosinophil|cbc|differential|glucose|creatinine|sodium|potassium|bun|a1c";
            $orderBy = "CASE WHEN LOWER(CONCAT_WS(' ', f.fact_type, f.label, f.value, d.original_filename)) REGEXP '" . $labTerms . "' THEN 0 ELSE 1 END, " . $orderBy;
        } elseif ($this->isMedicationPrompt($message)) {
            $medicationTerms = "medication|medications|meds|drug|dose|dosage|frequency|route|prescriber|metformin|lisinopril|atorvastatin|amlodipine|insulin";
            $orderBy = "CASE WHEN d.document_type = 'medication_list' OR LOWER(CONCAT_WS(' ', f.fact_type, f.label, f.value, d.original_filename)) REGEXP '" . $medicationTerms . "' THEN 0 ELSE 1 END, " . $orderBy;
        }
        $sql = "SELECT f.id, f.fact_type, f.label, f.value, f.unit, f.reference_range, f.abnormal_flag, f.recorded_at, " .
            "f.confidence, f.citation_json, d.document_type, d.original_filename, d.openemr_document_id, d.created_at " .
            "FROM agentforge_extracted_facts f " .
            "JOIN agentforge_documents d ON d.id = f.agentforge_document_id " .
            "JOIN documents od ON od.id = d.openemr_document_id AND od.foreign_id = f.pid AND od.deleted = 0 " .
            "WHERE f.pid = ? " .
            "ORDER BY " . $orderBy;
        $bind = [(int)$pid];
        if ($limit !== null) {
            $sql .= " LIMIT ?";
            $bind[] = $limit;
        }
        $result = sqlStatement($sql, $bind);
        $sources = [];
        while ($row = sqlFetchArray($result)) {
            $citation = json_decode((string)$row['citation_json'], true);
            $displayLabel = $this->canonicalFactLabel((string)$row['label'], is_array($citation) ? $citation : []);
            $valueParts = [
                $displayLabel,
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

    private function canonicalFactLabel(string $label, array $citation): string
    {
        $field = strtolower(trim((string)($citation['field_or_chunk_id'] ?? '')));
        $labels = [
            'phone' => 'Patient Phone',
            'patient_phone' => 'Patient Phone',
            'emergency_contact_phone' => 'Emergency Contact Phone',
            'pharmacy_phone' => 'Pharmacy Phone',
            'address' => 'Patient Address',
            'pharmacy_address' => 'Pharmacy Address',
        ];
        return $labels[$field] ?? $label;
    }

    private function isLabPrompt(string $message): bool
    {
        $normalized = strtolower($message);
        foreach (['lab', 'labs', 'cbc', 'hemoglobin', 'platelet', 'blood count', 'creatinine', 'glucose'] as $term) {
            if (strpos($normalized, $term) !== false) {
                return true;
            }
        }
        return false;
    }

    private function isMedicationPrompt(string $message): bool
    {
        $normalized = strtolower($message);
        foreach (['medication', 'medications', 'med list', 'medication list', 'meds', 'drug', 'dose'] as $term) {
            if (strpos($normalized, $term) !== false) {
                return true;
            }
        }
        return false;
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
