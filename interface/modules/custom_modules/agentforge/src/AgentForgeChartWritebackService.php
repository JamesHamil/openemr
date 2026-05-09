<?php

declare(strict_types=1);

/**
 * Writes AgentForge extracted document facts back into standard OpenEMR chart tables.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

namespace OpenEMR\Modules\AgentForge;

final class AgentForgeChartWritebackService
{
    /**
     * @param array<string, mixed> $payload
     * @return array<string, mixed>
     */
    public function writeBack(string $pid, int $agentforgeDocumentId, ?int $openEmrDocumentId, array $payload): array
    {
        $this->ensureAuditTable();

        $documentType = (string)($payload['document']['document_type'] ?? $payload['extraction']['document_type'] ?? '');
        $traceId = (string)($payload['extraction']['trace_id'] ?? '');
        $facts = is_array($payload['extraction']['extracted_facts'] ?? null) ? $payload['extraction']['extracted_facts'] : [];

        $summary = [
            'status' => 'skipped',
            'applied' => 0,
            'updated' => 0,
            'inserted' => 0,
            'skipped' => 0,
            'changed_fields' => [],
            'entries' => [],
        ];

        if ($pid === '' || !ctype_digit($pid) || $agentforgeDocumentId <= 0 || count($facts) === 0) {
            return $summary;
        }

        if ($documentType === 'intake_form') {
            $this->writeIntakeFacts($pid, $agentforgeDocumentId, $openEmrDocumentId, $facts, $traceId, $summary);
        } elseif ($documentType === 'medication_list') {
            $this->writeMedicationFacts($pid, $agentforgeDocumentId, $openEmrDocumentId, $facts, $traceId, $summary);
        } elseif ($documentType === 'lab_pdf') {
            $this->writeLabFacts($pid, $agentforgeDocumentId, $openEmrDocumentId, $facts, $traceId, $summary);
        }

        if ((int)$summary['applied'] > 0) {
            $summary['status'] = (int)$summary['skipped'] > 0 ? 'partial' : 'success';
        } elseif ((int)$summary['skipped'] > 0) {
            $summary['status'] = 'skipped';
        }

        return $summary;
    }

    private function ensureAuditTable(): void
    {
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
            "PRIMARY KEY (`id`)," .
            "KEY `idx_agentforge_writebacks_pid` (`pid`)," .
            "KEY `idx_agentforge_writebacks_document` (`agentforge_document_id`)," .
            "KEY `idx_agentforge_writebacks_fact` (`agentforge_fact_id`)" .
            ") ENGINE=InnoDB COMMENT='AgentForge chart writeback audit log'"
        );
    }

    /**
     * @param list<array<string, mixed>> $facts
     * @param array<string, mixed> $summary
     */
    private function writeIntakeFacts(
        string $pid,
        int $agentforgeDocumentId,
        ?int $openEmrDocumentId,
        array $facts,
        string $traceId,
        array &$summary
    ): void {
        $updates = [];
        foreach ($facts as $fact) {
            $keys = $this->factKeys($fact);
            $value = $this->factValue($fact);
            if ($value === '') {
                continue;
            }

            if ($this->matchesExact($keys, ['legal_name', 'patient_name', 'full_name', 'name'])) {
                $name = $this->parseName($value);
                if ($name['fname'] !== '') {
                    $updates[] = [$fact, 'fname', $name['fname']];
                }
                if ($name['lname'] !== '') {
                    $updates[] = [$fact, 'lname', $name['lname']];
                }
                continue;
            }

            if ($this->matchesExact($keys, ['dob', 'date_of_birth', 'birth_date'])) {
                $date = $this->normalizeDate($value);
                if ($date === '') {
                    $this->auditAndSummarize($pid, $agentforgeDocumentId, $openEmrDocumentId, $fact, 'patient_data', 'DOB', $pid, null, $value, 'skip', 'skipped', $traceId, 'Invalid DOB format; chart field was not updated.', $summary);
                } else {
                    $updates[] = [$fact, 'DOB', $date];
                }
                continue;
            }

            if ($this->matchesExact($keys, ['sex', 'sex_assigned_at_birth'])) {
                $updates[] = [$fact, 'sex', $this->normalizeSex($value)];
                continue;
            }

            if ($this->matchesExact($keys, ['address', 'patient_address', 'home_address'])) {
                foreach ($this->parseAddress($value) as $field => $fieldValue) {
                    if ($fieldValue !== '') {
                        $updates[] = [$fact, $field, $fieldValue];
                    }
                }
                continue;
            }

            $field = $this->intakeFieldForKeys($keys);
            if ($field !== '') {
                $updates[] = [$fact, $field, $value];
            }
        }

        foreach ($updates as [$fact, $field, $newValue]) {
            $this->updatePatientDataField($pid, $agentforgeDocumentId, $openEmrDocumentId, $fact, $field, (string)$newValue, $traceId, $summary);
        }
    }

    /**
     * @param list<array<string, mixed>> $facts
     * @param array<string, mixed> $summary
     */
    private function writeMedicationFacts(
        string $pid,
        int $agentforgeDocumentId,
        ?int $openEmrDocumentId,
        array $facts,
        string $traceId,
        array &$summary
    ): void {
        $this->retireAgentForgePrescriptionRows($pid, $agentforgeDocumentId, $openEmrDocumentId, $traceId, $summary);
        $activeRows = $this->activeMedicationIssueRows($pid);
        foreach ($facts as $fact) {
            if (!$this->isMedicationFact($fact)) {
                continue;
            }

            $medication = $this->parseMedicationFact($fact);
            if ($medication['drug'] === '') {
                $this->auditAndSummarize($pid, $agentforgeDocumentId, $openEmrDocumentId, $fact, 'lists', 'title', '', null, '', 'skip', 'skipped', $traceId, 'Medication fact had no usable drug name.', $summary);
                continue;
            }

            $match = $this->findMedicationIssueMatch($activeRows, $medication['drug'], $this->shortExternalId($agentforgeDocumentId, $fact));
            if ($match !== null) {
                $oldValue = trim((string)$match['title'] . ' ' . (string)($match['drug_dosage_instructions'] ?? ''));
                sqlStatement(
                    "UPDATE lists SET title = ?, comments = ?, date = NOW(), begdate = CURDATE(), activity = 1, " .
                    "enddate = NULL, external_id = ? WHERE id = ? AND pid = ?",
                    [
                        $medication['drug'],
                        $this->sourceNote($agentforgeDocumentId, $fact),
                        $this->shortExternalId($agentforgeDocumentId, $fact),
                        (int)$match['id'],
                        (int)$pid,
                    ]
                );
                $this->upsertListsMedication((int)$match['id'], $medication['instructions']);
                $this->auditAndSummarize($pid, $agentforgeDocumentId, $openEmrDocumentId, $fact, 'lists', 'title', (string)$match['id'], $oldValue, $medication['display'], 'update', 'applied', $traceId, 'Updated active medication list entry from medication-list document.', $summary);
                $activeRows = $this->activeMedicationIssueRows($pid);
                continue;
            }

            $recordId = sqlInsert(
                "INSERT INTO lists " .
                "(date, type, title, begdate, activity, comments, pid, user, groupname, external_id) " .
                "VALUES (NOW(), 'medication', ?, CURDATE(), 1, ?, ?, 'AgentForge', '', ?)",
                [
                    $medication['drug'],
                    $this->sourceNote($agentforgeDocumentId, $fact),
                    (int)$pid,
                    $this->shortExternalId($agentforgeDocumentId, $fact),
                ]
            );
            $this->upsertListsMedication((int)$recordId, $medication['instructions']);
            $this->auditAndSummarize($pid, $agentforgeDocumentId, $openEmrDocumentId, $fact, 'lists', 'title', (string)$recordId, null, $medication['display'], 'insert', 'applied', $traceId, 'Inserted active medication list entry from medication-list document.', $summary);
            $activeRows = $this->activeMedicationIssueRows($pid);
        }
    }

    /**
     * @param list<array<string, mixed>> $facts
     * @param array<string, mixed> $summary
     */
    private function writeLabFacts(
        string $pid,
        int $agentforgeDocumentId,
        ?int $openEmrDocumentId,
        array $facts,
        string $traceId,
        array &$summary
    ): void {
        $labFacts = array_values(array_filter($facts, function (array $fact): bool {
            return $this->isLabFact($fact);
        }));
        if (count($labFacts) === 0) {
            return;
        }

        $orderId = $this->ensureProcedureOrder($pid, $agentforgeDocumentId);
        $reportId = $this->ensureProcedureReport($orderId, $agentforgeDocumentId);

        foreach ($labFacts as $fact) {
            $label = trim((string)($fact['label'] ?? ''));
            $value = $this->factValue($fact);
            if ($label === '' || $value === '') {
                $this->auditAndSummarize($pid, $agentforgeDocumentId, $openEmrDocumentId, $fact, 'procedure_result', 'result', '', null, $value, 'skip', 'skipped', $traceId, 'Lab fact had no usable label or value.', $summary);
                continue;
            }

            $code = substr($this->normalizeLookup($label), 0, 31);
            $existing = sqlQuery(
                "SELECT procedure_result_id, result, units, `range`, abnormal FROM procedure_result " .
                "WHERE procedure_report_id = ? AND result_code = ? LIMIT 1",
                [$reportId, $code]
            );
            $oldValue = !empty($existing['procedure_result_id'])
                ? trim((string)$existing['result'] . ' ' . (string)$existing['units'] . ' ' . (string)$existing['range'] . ' ' . (string)$existing['abnormal'])
                : null;
            $params = [
                'S',
                $code,
                $label,
                gmdate('Y-m-d H:i:s'),
                'AgentForge',
                substr((string)($fact['unit'] ?? ''), 0, 31),
                $value,
                substr((string)($fact['reference_range'] ?? ''), 0, 255),
                substr((string)($fact['abnormal_flag'] ?? ''), 0, 31),
                $this->sourceNote($agentforgeDocumentId, $fact),
                $openEmrDocumentId,
                'final',
            ];

            if (!empty($existing['procedure_result_id'])) {
                sqlStatement(
                    "UPDATE procedure_result SET result_data_type = ?, result_code = ?, result_text = ?, date = ?, facility = ?, " .
                    "units = ?, result = ?, `range` = ?, abnormal = ?, comments = ?, document_id = ?, result_status = ? " .
                    "WHERE procedure_result_id = ?",
                    array_merge($params, [(int)$existing['procedure_result_id']])
                );
                $recordId = (string)$existing['procedure_result_id'];
                $action = 'update';
            } else {
                $recordId = (string)sqlInsert(
                    "INSERT INTO procedure_result " .
                    "(procedure_report_id, result_data_type, result_code, result_text, date, facility, units, result, `range`, abnormal, comments, document_id, result_status) " .
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    array_merge([$reportId], $params)
                );
                $action = 'insert';
            }

            $this->auditAndSummarize($pid, $agentforgeDocumentId, $openEmrDocumentId, $fact, 'procedure_result', 'result', $recordId, $oldValue, trim($label . ' ' . $value), $action, 'applied', $traceId, 'Upserted lab result from lab PDF document.', $summary);
        }
    }

    private function updatePatientDataField(
        string $pid,
        int $agentforgeDocumentId,
        ?int $openEmrDocumentId,
        array $fact,
        string $field,
        string $newValue,
        string $traceId,
        array &$summary
    ): void {
        $allowedFields = [
            'fname', 'lname', 'DOB', 'sex', 'street', 'street_line_2', 'city', 'state',
            'postal_code', 'phone_home', 'phone_cell', 'email', 'occupation',
        ];
        if (!in_array($field, $allowedFields, true) || $newValue === '') {
            return;
        }

        $row = sqlQuery("SELECT `" . $field . "` FROM patient_data WHERE pid = ? LIMIT 1", [(int)$pid]);
        if (!is_array($row) || !array_key_exists($field, $row)) {
            $this->auditAndSummarize($pid, $agentforgeDocumentId, $openEmrDocumentId, $fact, 'patient_data', $field, $pid, null, $newValue, 'skip', 'skipped', $traceId, 'Patient field was unavailable.', $summary);
            return;
        }

        $oldValue = (string)($row[$field] ?? '');
        if ($oldValue === $newValue) {
            $this->auditAndSummarize($pid, $agentforgeDocumentId, $openEmrDocumentId, $fact, 'patient_data', $field, $pid, $oldValue, $newValue, 'skip', 'skipped', $traceId, 'Chart already matched extracted value.', $summary);
            return;
        }

        sqlStatement("UPDATE patient_data SET `" . $field . "` = ? WHERE pid = ?", [$newValue, (int)$pid]);
        $this->auditAndSummarize($pid, $agentforgeDocumentId, $openEmrDocumentId, $fact, 'patient_data', $field, $pid, $oldValue, $newValue, 'update', 'applied', $traceId, 'Updated patient chart field from intake form.', $summary);
    }

    /**
     * @return list<array<string, mixed>>
     */
    private function activeMedicationIssueRows(string $pid): array
    {
        $rows = [];
        $result = sqlStatement(
            "SELECT lists.id, lists.title, lists.comments, lists.external_id, lists_medication.drug_dosage_instructions " .
            "FROM lists LEFT JOIN lists_medication ON lists_medication.list_id = lists.id " .
            "WHERE lists.pid = ? AND lists.type = 'medication' AND lists.activity = 1 " .
            "AND (lists.enddate IS NULL OR lists.enddate = '' OR lists.enddate > NOW())",
            [(int)$pid]
        );
        while ($row = sqlFetchArray($result)) {
            $rows[] = $row;
        }
        return $rows;
    }

    /**
     * @param list<array<string, mixed>> $rows
     */
    private function findMedicationIssueMatch(array $rows, string $drug, string $externalId): ?array
    {
        $needle = $this->normalizeMedicationName($drug);
        if ($needle === '') {
            return null;
        }
        foreach ($rows as $row) {
            if ($externalId !== '' && (string)($row['external_id'] ?? '') === $externalId) {
                return $row;
            }
            $candidate = $this->normalizeMedicationName((string)($row['title'] ?? ''));
            if ($candidate === '' || $candidate === 'medication') {
                continue;
            }
            if ($candidate === $needle || str_contains($candidate, $needle) || str_contains($needle, $candidate)) {
                return $row;
            }
        }
        return null;
    }

    private function upsertListsMedication(int $listId, string $instructions): void
    {
        $existing = sqlQuery(
            "SELECT id FROM lists_medication WHERE list_id = ? LIMIT 1",
            [$listId]
        );
        if (!empty($existing['id'])) {
            sqlStatement(
                "UPDATE lists_medication SET drug_dosage_instructions = ?, is_primary_record = 0 " .
                "WHERE list_id = ?",
                [$instructions, $listId]
            );
            return;
        }

        sqlStatement(
            "INSERT INTO lists_medication " .
            "(list_id, drug_dosage_instructions, usage_category_title, request_intent_title, is_primary_record) " .
            "VALUES (?, ?, '', '', 0)",
            [$listId, $instructions]
        );
    }

    private function retireAgentForgePrescriptionRows(
        string $pid,
        int $agentforgeDocumentId,
        ?int $openEmrDocumentId,
        string $traceId,
        array &$summary
    ): void {
        $result = sqlStatement(
            "SELECT id, drug, dosage, drug_dosage_instructions FROM prescriptions " .
            "WHERE patient_id = ? AND active = 1 AND external_id LIKE 'agentforge-document-%'",
            [(int)$pid]
        );
        while ($row = sqlFetchArray($result)) {
            $oldValue = trim((string)$row['drug'] . ' ' . (string)($row['dosage'] ?? '') . ' ' . (string)($row['drug_dosage_instructions'] ?? ''));
            sqlStatement(
                "UPDATE prescriptions SET active = 0, date_modified = NOW() WHERE id = ? AND patient_id = ?",
                [(int)$row['id'], (int)$pid]
            );
            $this->auditAndSummarize($pid, $agentforgeDocumentId, $openEmrDocumentId, [], 'prescriptions', 'active', (string)$row['id'], $oldValue, '0', 'deactivate', 'applied', $traceId, 'Retired prior AgentForge prescription entry; medication-list documents now write to Medications.', $summary);
        }
    }

    private function ensureProcedureOrder(string $pid, int $agentforgeDocumentId): int
    {
        $controlId = 'agentforge-document-' . $agentforgeDocumentId;
        $existing = sqlQuery(
            "SELECT procedure_order_id FROM procedure_order WHERE patient_id = ? AND control_id = ? LIMIT 1",
            [(int)$pid, $controlId]
        );
        if (!empty($existing['procedure_order_id'])) {
            return (int)$existing['procedure_order_id'];
        }

        return (int)sqlInsert(
            "INSERT INTO procedure_order " .
            "(provider_id, patient_id, encounter_id, date_collected, date_ordered, order_priority, order_status, " .
            "patient_instructions, activity, control_id, lab_id, specimen_type, specimen_location, specimen_volume, " .
            "clinical_hx, procedure_order_type, order_diagnosis, order_psc, order_abn, order_intent, collector_id) " .
            "VALUES (0, ?, 0, NOW(), NOW(), '', 'received', '', 1, ?, 0, '', '', '', '', 'laboratory_test', '', '', '', 'order', 0)",
            [(int)$pid, $controlId]
        );
    }

    private function ensureProcedureReport(int $orderId, int $agentforgeDocumentId): int
    {
        $specimen = 'agentforge-document-' . $agentforgeDocumentId;
        $existing = sqlQuery(
            "SELECT procedure_report_id FROM procedure_report WHERE procedure_order_id = ? AND specimen_num = ? LIMIT 1",
            [$orderId, $specimen]
        );
        if (!empty($existing['procedure_report_id'])) {
            return (int)$existing['procedure_report_id'];
        }

        return (int)sqlInsert(
            "INSERT INTO procedure_report " .
            "(procedure_order_id, procedure_order_seq, date_collected, date_report, source, specimen_num, report_status, review_status, report_notes) " .
            "VALUES (?, 1, NOW(), NOW(), 0, ?, 'received', 'received', 'AgentForge uploaded lab document')",
            [$orderId, $specimen]
        );
    }

    private function auditAndSummarize(
        string $pid,
        int $agentforgeDocumentId,
        ?int $openEmrDocumentId,
        array $fact,
        string $targetTable,
        string $targetField,
        string $targetRecordId,
        ?string $oldValue,
        string $newValue,
        string $action,
        string $status,
        string $traceId,
        string $message,
        array &$summary
    ): void {
        sqlStatement(
            "INSERT INTO agentforge_chart_writebacks " .
            "(pid, agentforge_document_id, openemr_document_id, agentforge_fact_id, target_table, target_field, " .
            "target_record_id, old_value, new_value, action, status, trace_id, message) " .
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (int)$pid,
                $agentforgeDocumentId,
                $openEmrDocumentId,
                $this->factId($fact),
                $targetTable,
                $targetField,
                $targetRecordId,
                $oldValue,
                $newValue,
                $action,
                $status,
                $traceId,
                $message,
            ]
        );

        if ($status === 'applied') {
            $summary['applied'] = (int)$summary['applied'] + 1;
            if ($action === 'insert') {
                $summary['inserted'] = (int)$summary['inserted'] + 1;
            } else {
                $summary['updated'] = (int)$summary['updated'] + 1;
            }
            $summary['changed_fields'][] = $targetTable . '.' . $targetField;
        } else {
            $summary['skipped'] = (int)$summary['skipped'] + 1;
        }

        if (count($summary['entries']) < 12) {
            $summary['entries'][] = [
                'target' => $targetTable . ($targetField !== '' ? '.' . $targetField : ''),
                'record_id' => $targetRecordId,
                'action' => $action,
                'status' => $status,
                'message' => $message,
            ];
        }
    }

    /**
     * @return list<string>
     */
    private function factKeys(array $fact): array
    {
        $citation = is_array($fact['citation'] ?? null) ? $fact['citation'] : [];
        $values = [
            $fact['fact_type'] ?? '',
            $fact['label'] ?? '',
            $citation['field_or_chunk_id'] ?? '',
        ];
        $keys = [];
        foreach ($values as $value) {
            $normalized = $this->normalizeLookup((string)$value);
            if ($normalized !== '') {
                $keys[] = $normalized;
            }
        }
        return array_values(array_unique($keys));
    }

    private function intakeFieldForKeys(array $keys): string
    {
        $map = [
            'street' => ['street', 'address_line_1', 'address_1'],
            'street_line_2' => ['street_line_2', 'address_line_2', 'address_2', 'apt', 'apartment'],
            'city' => ['city'],
            'state' => ['state'],
            'postal_code' => ['postal_code', 'zip', 'zip_code'],
            'phone_home' => ['phone', 'phone_number', 'patient_phone', 'home_phone', 'telephone', 'primary_phone'],
            'phone_cell' => ['cell', 'cell_phone', 'mobile', 'mobile_phone'],
            'email' => ['email', 'email_address'],
            'occupation' => ['occupation', 'job'],
        ];
        foreach ($map as $field => $aliases) {
            if ($this->matchesExact($keys, $aliases)) {
                return $field;
            }
        }
        return '';
    }

    private function matchesExact(array $keys, array $needles): bool
    {
        foreach ($keys as $key) {
            if (in_array($key, $needles, true)) {
                return true;
            }
        }
        return false;
    }

    private function matchesAny(array $keys, array $needles): bool
    {
        foreach ($keys as $key) {
            foreach ($needles as $needle) {
                if ($key === $needle || str_contains($key, $needle) || str_contains($needle, $key)) {
                    return true;
                }
            }
        }
        return false;
    }

    private function factValue(array $fact): string
    {
        return trim((string)($fact['value'] ?? ''));
    }

    private function factId(array $fact): ?int
    {
        $id = (string)($fact['id'] ?? '');
        return ctype_digit($id) ? (int)$id : null;
    }

    /**
     * @return array{fname: string, lname: string}
     */
    private function parseName(string $value): array
    {
        $clean = trim(preg_replace('/\s+/', ' ', $value) ?: '');
        if (str_contains($clean, ',')) {
            [$last, $rest] = array_map('trim', explode(',', $clean, 2));
            $restParts = preg_split('/\s+/', $rest) ?: [];
            return [
                'fname' => trim((string)($restParts[0] ?? '')),
                'lname' => $last,
            ];
        }
        $parts = $clean === '' ? [] : explode(' ', $clean, 2);
        return [
            'fname' => trim((string)($parts[0] ?? '')),
            'lname' => trim((string)($parts[1] ?? '')),
        ];
    }

    private function normalizeDate(string $value): string
    {
        $clean = trim($value);
        foreach (['Y-m-d', 'm/d/Y', 'n/j/Y', 'm-d-Y', 'n-j-Y'] as $format) {
            $date = \DateTimeImmutable::createFromFormat('!' . $format, $clean);
            if ($date instanceof \DateTimeImmutable && $date->format($format) === $clean) {
                return $date->format('Y-m-d');
            }
        }
        return '';
    }

    private function normalizeSex(string $value): string
    {
        $normalized = strtolower(trim($value));
        if (in_array($normalized, ['m', 'male'], true)) {
            return 'Male';
        }
        if (in_array($normalized, ['f', 'female'], true)) {
            return 'Female';
        }
        return trim($value);
    }

    /**
     * @return array<string, string>
     */
    private function parseAddress(string $value): array
    {
        $parts = array_values(array_filter(array_map('trim', explode(',', $value))));
        if (count($parts) < 3) {
            return ['street' => $value];
        }

        $last = array_pop($parts);
        $city = array_pop($parts);
        $state = '';
        $postalCode = '';
        if (preg_match('/^([A-Za-z]{2})\s+(.+)$/', $last, $matches) === 1) {
            $state = strtoupper($matches[1]);
            $postalCode = trim($matches[2]);
        }

        return [
            'street' => (string)($parts[0] ?? ''),
            'street_line_2' => count($parts) > 1 ? implode(', ', array_slice($parts, 1)) : '',
            'city' => $city,
            'state' => $state,
            'postal_code' => $postalCode,
        ];
    }

    private function isMedicationFact(array $fact): bool
    {
        return $this->matchesAny($this->factKeys($fact), ['medication', 'medication_list', 'drug']);
    }

    /**
     * @return array{drug: string, dosage: string, instructions: string, display: string}
     */
    private function parseMedicationFact(array $fact): array
    {
        $label = trim((string)($fact['label'] ?? ''));
        $value = $this->factValue($fact);
        $drug = $label;
        if ($drug === '' || in_array($this->normalizeLookup($drug), ['medication', 'drug', 'uploaded_medication_list'], true)) {
            $drug = trim((string)preg_replace('/[;|].*$/', '', $value));
        }

        $doseParts = preg_split('/\s*[;|]\s*/', $value);
        $dosage = '';
        $instructions = '';
        if (is_array($doseParts) && count($doseParts) > 0) {
            if ($this->normalizeMedicationName((string)$doseParts[0]) === $this->normalizeMedicationName($drug)) {
                $dosage = trim((string)($doseParts[1] ?? ''));
                $instructions = trim(implode('; ', array_slice($doseParts, 2)));
            } else {
                $dosage = trim((string)($doseParts[0] ?? ''));
                $instructions = trim(implode('; ', array_slice($doseParts, 1)));
            }
        }
        if ($instructions === '' && $dosage !== '' && preg_match('/\b(daily|twice|bedtime|needed|hours|weeks|day|night|mouth|puffs)\b/i', $dosage) === 1) {
            $instructions = $dosage;
            $dosage = '';
        }

        $display = trim($drug . ($dosage !== '' ? ' ' . $dosage : '') . ($instructions !== '' ? '; ' . $instructions : ''));
        return [
            'drug' => trim($drug),
            'dosage' => $dosage,
            'instructions' => $instructions,
            'display' => $display,
        ];
    }

    private function isLabFact(array $fact): bool
    {
        return !$this->matchesAny($this->factKeys($fact), ['uploaded_lab_pdf']);
    }

    private function sourceNote(int $agentforgeDocumentId, array $fact): string
    {
        $factId = $this->factId($fact);
        return 'AgentForge document ' . $agentforgeDocumentId . ($factId !== null ? ' fact ' . $factId : '');
    }

    private function externalId(int $agentforgeDocumentId, array $fact): string
    {
        return 'agentforge-document-' . $agentforgeDocumentId . ':fact-' . (string)($this->factId($fact) ?? 'unknown');
    }

    private function shortExternalId(int $agentforgeDocumentId, array $fact): string
    {
        $factId = $this->factId($fact);
        return 'af-' . $agentforgeDocumentId . '-' . ($factId !== null ? (string)$factId : 'x');
    }

    private function normalizeLookup(string $value): string
    {
        $value = strtolower(trim($value));
        $value = preg_replace('/[^a-z0-9]+/', '_', $value) ?: '';
        return trim($value, '_');
    }

    private function normalizeMedicationName(string $value): string
    {
        $value = strtolower($value);
        $value = preg_replace('/\b\d+(\.\d+)?\b/', ' ', $value) ?: '';
        $value = preg_replace('/\b(mg|mcg|g|ml|units|unit|tablet|tab|capsule|cap|oral|po|daily|twice|hfa|puff|puffs)\b/', ' ', $value) ?: '';
        $value = preg_replace('/[^a-z0-9]+/', ' ', $value) ?: '';
        return trim(preg_replace('/\s+/', ' ', $value) ?: '');
    }
}
