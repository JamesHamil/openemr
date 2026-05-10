<?php

namespace OpenEMR\Modules\AgentForge;

require_once(__DIR__ . "/AgentForgeDocumentStore.php");

class AgentForgeEvidenceCollector
{
    public function collect(string $pid, string $encounterId = '', string $message = ''): array
    {
        $sources = [];
        $statuses = [];

        $this->collectAdapter('patient_snapshot', function () use ($pid, &$sources, &$statuses): void {
            $this->collectPatientSnapshot($pid, $sources, $statuses);
        }, $statuses);
        $this->collectAdapter('problem_list', function () use ($pid, &$sources, &$statuses): void {
            $this->collectProblems($pid, $sources, $statuses);
        }, $statuses);
        $this->collectAdapter('allergies', function () use ($pid, &$sources, &$statuses): void {
            $this->collectAllergies($pid, $sources, $statuses);
        }, $statuses);
        $this->collectAdapter('medications', function () use ($pid, $message, &$sources, &$statuses): void {
            $this->collectMedications($pid, $message, $sources, $statuses);
        }, $statuses);
        $this->collectAdapter('vitals', function () use ($pid, &$sources, &$statuses): void {
            $this->collectVitals($pid, $sources, $statuses);
        }, $statuses);
        $this->collectAdapter('labs', function () use ($pid, &$sources, &$statuses): void {
            $this->collectLabs($pid, $sources, $statuses);
        }, $statuses);
        $this->collectAdapter('recent_notes', function () use ($pid, &$sources, &$statuses): void {
            $this->collectNotes($pid, $sources, $statuses);
        }, $statuses);
        $this->collectAdapter('encounters', function () use ($pid, &$sources, &$statuses): void {
            $this->collectEncounters($pid, $sources, $statuses);
        }, $statuses);
        $this->collectAdapter('agentforge_documents', function () use ($pid, $message, &$sources, &$statuses): void {
            $this->collectExtractedDocumentFacts($pid, $message, $sources, $statuses);
        }, $statuses);

        return [
            'id' => 'bundle-' . bin2hex(random_bytes(8)),
            'created_at' => gmdate('c'),
            'patient_context' => [
                'patient_id' => $pid,
                'encounter_id' => $encounterId,
            ],
            'sources' => $sources,
            'adapter_status' => $statuses,
        ];
    }

    private function collectPatientSnapshot(string $pid, array &$sources, array &$statuses): void
    {
        $row = sqlQuery("SELECT fname, lname, DOB, sex FROM patient_data WHERE pid = ?", [$pid]);
        if (empty($row)) {
            $statuses[] = $this->status('patient_snapshot', 'failed', 'Patient row was not found.');
            return;
        }

        $name = trim(($row['fname'] ?? '') . ' ' . ($row['lname'] ?? ''));
        $this->addSource($sources, 'patient-name-' . $pid, 'demographic', 'patient_data.fname_lname', $name);
        if (!empty($row['DOB'])) {
            $this->addSource($sources, 'patient-dob-' . $pid, 'demographic', 'patient_data.DOB', (string)$row['DOB']);
        }
        if (!empty($row['sex'])) {
            $this->addSource($sources, 'patient-sex-' . $pid, 'demographic', 'patient_data.sex', (string)$row['sex']);
        }
        $statuses[] = $this->status('patient_snapshot', 'success');
    }

    private function collectProblems(string $pid, array &$sources, array &$statuses): void
    {
        $count = $this->collectActiveIssueSources($pid, 'medical_problem', 'problem', 'problem', $sources);
        $statuses[] = $count === 0
            ? $this->status('problem_list', 'unavailable', 'No active problem-list records found in retrieved lists.')
            : $this->status('problem_list', 'success');
    }

    private function collectAllergies(string $pid, array &$sources, array &$statuses): void
    {
        $count = $this->collectActiveIssueSources($pid, 'allergy', 'allergy', 'allergy', $sources);
        $statuses[] = $count === 0
            ? $this->status('allergies', 'unavailable', 'No active allergy records found in retrieved lists.')
            : $this->status('allergies', 'success');
    }

    private function collectActiveIssueSources(
        string $pid,
        string $type,
        string $recordType,
        string $sourcePrefix,
        array &$sources
    ): int
    {
        // Match the patient dashboard semantics for active issues:
        // unresolved outcome and blank/future end date.
        if ($type === 'medication') {
            $result = sqlStatement(
                "SELECT lists.id, lists.title, lists.begdate, lists.date, lists.enddate, lists.outcome, " .
                "lists_medication.drug_dosage_instructions " .
                "FROM lists LEFT JOIN lists_medication ON lists_medication.list_id = lists.id " .
                "WHERE lists.pid = ? AND lists.type = ? " .
                "ORDER BY COALESCE(lists.date, lists.begdate) DESC",
                [$pid, $type]
            );
        } else {
            $result = sqlStatement(
                "SELECT id, title, begdate, date, enddate, outcome " .
                "FROM lists WHERE pid = ? AND type = ? " .
                "ORDER BY COALESCE(date, begdate) DESC",
                [$pid, $type]
            );
        }
        $count = 0;
        while ($row = sqlFetchArray($result)) {
            if (!$this->isActiveIssueRow($row) || empty($row['title'])) {
                continue;
            }
            $count++;
            $this->addSource(
                $sources,
                $sourcePrefix . '-' . (string)$row['id'],
                $recordType,
                'lists.title',
                    trim((string)$row['title'] . (!empty($row['drug_dosage_instructions']) ? '; instructions ' . (string)$row['drug_dosage_instructions'] : '')),
                (string)($row['date'] ?: $row['begdate'] ?: gmdate('c')),
                '',
                [
                    'status' => 'current',
                    'source_table' => 'lists',
                    'issue_type' => $type,
                ]
            );
        }
        return $count;
    }

    private function collectMedications(string $pid, string $message, array &$sources, array &$statuses): void
    {
        $count = $this->collectActiveIssueSources($pid, 'medication', 'medication', 'medication-list', $sources);
        if ($count === 0) {
            $count = $this->collectActivePrescriptions($pid, $sources);
        } elseif ($this->isMedicationPrompt($message)) {
            $count += $this->collectActivePrescriptions($pid, $sources);
        }
        $statuses[] = $count === 0
            ? $this->status('medications', 'unavailable', 'No active medications found in retrieved medication lists or prescriptions.')
            : $this->status('medications', 'success');

        if ($this->isMedicationReconciliationPrompt($message)) {
            $historyCount = $this->collectHistoricalPrescriptions($pid, $sources);
            $statuses[] = $historyCount === 0
                ? $this->status('medication_history', 'unavailable', 'No historical prescriptions found for medication reconciliation.')
                : $this->status('medication_history', 'success');
        }
    }

    private function collectActivePrescriptions(string $pid, array &$sources): int
    {
        $result = sqlStatement(
            "SELECT id, drug, dosage, drug_dosage_instructions, external_id, date_added, start_date FROM prescriptions WHERE patient_id = ? AND active = 1 " .
            "ORDER BY COALESCE(date_added, start_date) DESC",
            [$pid]
        );
        $count = 0;
        while ($row = sqlFetchArray($result)) {
            if (!empty($row['drug'])) {
                $valueParts = [(string)$row['drug']];
                if (!empty($row['dosage'])) {
                    $valueParts[] = 'dosage ' . (string)$row['dosage'];
                }
                if (!empty($row['drug_dosage_instructions'])) {
                    $valueParts[] = 'instructions ' . (string)$row['drug_dosage_instructions'];
                }
                $count++;
                $this->addSource(
                    $sources,
                    'medication-rx-' . (string)$row['id'],
                    'medication',
                    'prescriptions.drug',
                    implode('; ', $valueParts),
                    (string)($row['date_added'] ?: $row['start_date'] ?: gmdate('c')),
                    '',
                    [
                        'status' => 'current',
                        'source_table' => 'prescriptions',
                        'active' => '1',
                        'external_id' => (string)($row['external_id'] ?? ''),
                    ]
                );
            }
        }
        return $count;
    }

    private function collectHistoricalPrescriptions(string $pid, array &$sources): int
    {
        $result = sqlStatement(
            "SELECT id, drug, date_added, start_date, active FROM prescriptions WHERE patient_id = ? AND active = 0 " .
            "ORDER BY COALESCE(date_added, start_date) DESC",
            [$pid]
        );
        $count = 0;
        while ($row = sqlFetchArray($result)) {
            if (!empty($row['drug'])) {
                $count++;
                $this->addSource(
                    $sources,
                    'medication-history-rx-' . (string)$row['id'],
                    'medication',
                    'prescriptions.drug',
                    (string)$row['drug'],
                    (string)($row['date_added'] ?: $row['start_date'] ?: gmdate('c')),
                    '',
                    [
                        'status' => 'historical',
                        'source_table' => 'prescriptions',
                        'active' => '0',
                    ]
                );
            }
        }
        return $count;
    }

    private function collectVitals(string $pid, array &$sources, array &$statuses): void
    {
        $result = sqlStatement(
            "SELECT id, date, bps, bpd, pulse, temperature, weight, height FROM form_vitals WHERE pid = ? ORDER BY date DESC",
            [$pid]
        );
        $count = 0;
        while ($row = sqlFetchArray($result)) {
            foreach (['bps', 'bpd', 'pulse', 'temperature', 'weight', 'height'] as $field) {
                if ($row[$field] !== null && $row[$field] !== '') {
                    $count++;
                    $this->addSource(
                        $sources,
                        'vital-' . (string)$row['id'] . '-' . $field,
                        'vital',
                        'form_vitals.' . $field,
                        $field . ' ' . (string)$row[$field],
                        (string)($row['date'] ?: gmdate('c'))
                    );
                }
            }
        }
        $statuses[] = $count === 0
            ? $this->status('vitals', 'unavailable', 'No vitals found in retrieved form_vitals records.')
            : $this->status('vitals', 'success');
    }

    private function collectLabs(string $pid, array &$sources, array &$statuses): void
    {
        $result = sqlStatement(
            "SELECT pr.procedure_result_id, pr.result_text, pr.result, pr.units, pr.range, pr.abnormal, pr.result_status, " .
            "COALESCE(pr.date, prep.date_report, prep.date_collected, po.date_collected, po.date_ordered) AS lab_date, " .
            "poc.procedure_name, poc.procedure_code " .
            "FROM procedure_result pr " .
            "JOIN procedure_report prep ON pr.procedure_report_id = prep.procedure_report_id " .
            "JOIN procedure_order po ON prep.procedure_order_id = po.procedure_order_id " .
            "LEFT JOIN procedure_order_code poc ON po.procedure_order_id = poc.procedure_order_id " .
            "AND prep.procedure_order_seq = poc.procedure_order_seq " .
            "WHERE po.patient_id = ? " .
            "AND LOWER(COALESCE(pr.result_text, '')) NOT REGEXP 'address|date of birth|dob|mrn|legal name|^name$|ordering provider|patient phone|report date|^sex$|specimen type|^status$|accession|loinc|interpretation' " .
            "AND (TRIM(COALESCE(pr.units, '')) <> '' " .
            "OR TRIM(COALESCE(pr.`range`, '')) <> '' " .
            "OR UPPER(TRIM(COALESCE(pr.abnormal, ''))) IN ('H', 'L', 'N', 'HIGH', 'LOW', 'NORMAL', 'ABNORMAL') " .
            "OR LOWER(COALESCE(pr.result_text, '')) REGEXP 'albumin|alkaline phosphatase|alt|ast|bilirubin|bun|calcium|chloride|co2|creatinine|egfr|glucose|hematocrit|hemoglobin|lymphocyte|mcv|metamyelocyte|monocyte|neutrophil|platelet|potassium|promyelocyte|rbc|sodium|total protein|blast|wbc') " .
            "ORDER BY COALESCE(pr.date, prep.date_report, prep.date_collected, po.date_collected, po.date_ordered) DESC",
            [$pid]
        );

        $count = 0;
        while ($row = sqlFetchArray($result)) {
            $resultText = trim((string)($row['result_text'] ?? ''));
            $procedureName = trim((string)($row['procedure_name'] ?? ''));
            $label = $resultText !== '' ? $resultText : ($procedureName !== '' ? $procedureName : 'Lab result');
            $valueParts = [$label];

            if (!empty($row['result'])) {
                $valueParts[] = 'result ' . trim((string)$row['result']);
            }
            if (!empty($row['units'])) {
                $valueParts[] = 'units ' . trim((string)$row['units']);
            }
            if (!empty($row['range'])) {
                $valueParts[] = 'range ' . trim((string)$row['range']);
            }
            if (!empty($row['abnormal'])) {
                $valueParts[] = 'abnormal ' . trim((string)$row['abnormal']);
            }
            if (!empty($row['result_status'])) {
                $valueParts[] = 'status ' . trim((string)$row['result_status']);
            }

            $count++;
            $this->addSource(
                $sources,
                'lab-' . (string)$row['procedure_result_id'],
                'lab',
                'procedure_result.result',
                implode('; ', $valueParts),
                (string)($row['lab_date'] ?: gmdate('c'))
            );
        }

        $statuses[] = $count === 0
            ? $this->status('labs', 'unavailable', 'No recent lab results found in retrieved procedure result records.')
            : $this->status('labs', 'success');
    }

    private function collectNotes(string $pid, array &$sources, array &$statuses): void
    {
        $result = sqlStatement(
            "SELECT id, date, body FROM pnotes WHERE pid = ? ORDER BY date DESC",
            [$pid]
        );
        $count = 0;
        while ($row = sqlFetchArray($result)) {
            if (!empty($row['body'])) {
                $count++;
                $body = trim(strip_tags((string)$row['body']));
                $this->addSource(
                    $sources,
                    'note-' . (string)$row['id'],
                    'note',
                    'pnotes.body',
                    substr($body, 0, 600),
                    (string)($row['date'] ?: gmdate('c')),
                    substr($body, 0, 240)
                );
            }
        }
        $statuses[] = $count === 0
            ? $this->status('recent_notes', 'unavailable', 'No patient notes found in retrieved pnotes records.')
            : $this->status('recent_notes', 'success');
    }

    private function collectEncounters(string $pid, array &$sources, array &$statuses): void
    {
        $result = sqlStatement(
            "SELECT fe.encounter, fe.date, fe.reason, pc.pc_catname " .
            "FROM form_encounter fe " .
            "LEFT JOIN openemr_postcalendar_categories pc ON pc.pc_catid = fe.pc_catid " .
            "WHERE fe.pid = ? " .
            "ORDER BY fe.date DESC",
            [$pid]
        );

        $count = 0;
        while ($row = sqlFetchArray($result)) {
            $encounterId = trim((string)($row['encounter'] ?? ''));
            $date = trim((string)($row['date'] ?? ''));
            if ($encounterId === '' || $date === '') {
                continue;
            }

            $category = trim(strip_tags((string)($row['pc_catname'] ?? '')));
            $reason = trim(strip_tags((string)($row['reason'] ?? '')));
            $parts = array_values(array_filter(
                [$date, $category, $reason],
                static function (string $part): bool {
                    return $part !== '';
                }
            ));

            $count++;
            $this->addSource(
                $sources,
                'encounter-' . $encounterId,
                'encounter',
                'form_encounter.date_reason',
                implode('; ', $parts),
                $date,
                $reason,
                [
                    'source_table' => 'form_encounter',
                    'encounter_id' => $encounterId,
                    'category' => $category,
                ]
            );
        }

        $statuses[] = $count === 0
            ? $this->status('encounters', 'unavailable', 'No encounters found in retrieved form_encounter records.')
            : $this->status('encounters', 'success');
    }

    private function collectExtractedDocumentFacts(string $pid, string $message, array &$sources, array &$statuses): void
    {
        $store = new AgentForgeDocumentStore();
        $documentSources = $store->recentFactSources($pid, null, $message);
        foreach ($documentSources as $source) {
            $sources[] = $source;
        }
        $statuses[] = count($documentSources) === 0
            ? $this->status('agentforge_documents', 'unavailable', 'No AgentForge extracted document facts found for this patient.')
            : $this->status('agentforge_documents', 'success');
    }

    private function addSource(
        array &$sources,
        string $id,
        string $recordType,
        string $fieldPath,
        string $value,
        string $recordedAt = '',
        string $noteSpan = '',
        array $metadata = []
    ): void {
        $source = [
            'id' => $id,
            'record_type' => $recordType,
            'recorded_at' => $recordedAt ?: gmdate('c'),
            'field_path' => $fieldPath,
            'value' => $value,
        ];
        if ($noteSpan !== '') {
            $source['note_span'] = $noteSpan;
        }
        if (!empty($metadata)) {
            $source['metadata'] = array_map('strval', $metadata);
        }
        $sources[] = $source;
    }

    private function collectAdapter(string $adapter, callable $collector, array &$statuses): void
    {
        $started = microtime(true);
        $statusCount = count($statuses);
        try {
            $collector();
        } catch (\Throwable $e) {
            $statuses[] = $this->status($adapter, 'failed', $e->getMessage());
        }

        $latencyMs = (int)round((microtime(true) - $started) * 1000);
        if (count($statuses) === $statusCount) {
            $statuses[] = $this->status($adapter, 'success', '', $latencyMs);
            return;
        }

        for ($index = $statusCount; $index < count($statuses); $index++) {
            if (!isset($statuses[$index]['latency_ms'])) {
                $statuses[$index]['latency_ms'] = $latencyMs;
            }
        }
    }

    private function status(string $adapter, string $status, string $reason = '', ?int $latencyMs = null): array
    {
        $payload = [
            'adapter' => $adapter,
            'status' => $status,
            'reason' => $reason,
        ];
        if ($latencyMs !== null) {
            $payload['latency_ms'] = $latencyMs;
        }
        return $payload;
    }

    private function isActiveIssueRow(array $row): bool
    {
        $outcome = isset($row['outcome']) ? (int)$row['outcome'] : 0;
        if ($outcome === 1) {
            return false;
        }

        $endDate = trim((string)($row['enddate'] ?? ''));
        if ($endDate === '' || $endDate === '0000-00-00') {
            return true;
        }

        $endTs = strtotime($endDate);
        return $endTs !== false && $endTs > time();
    }

    private function isMedicationReconciliationPrompt(string $message): bool
    {
        $normalized = strtolower($message);
        return strpos($normalized, 'medication reconciliation') !== false
            || strpos($normalized, 'med rec') !== false
            || strpos($normalized, 'reconciliation') !== false;
    }

    private function isMedicationPrompt(string $message): bool
    {
        $normalized = strtolower($message);
        return strpos($normalized, 'medication') !== false
            || strpos($normalized, 'medications') !== false
            || strpos($normalized, 'meds') !== false
            || strpos($normalized, 'prescription') !== false
            || $this->isMedicationReconciliationPrompt($message);
    }
}
