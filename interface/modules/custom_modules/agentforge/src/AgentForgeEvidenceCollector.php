<?php

namespace OpenEMR\Modules\AgentForge;

class AgentForgeEvidenceCollector
{
    public function collect(string $pid, string $encounterId = ''): array
    {
        $sources = [];
        $statuses = [];

        $this->collectPatientSnapshot($pid, $sources, $statuses);
        $this->collectProblems($pid, $sources, $statuses);
        $this->collectAllergies($pid, $sources, $statuses);
        $this->collectMedications($pid, $sources, $statuses);
        $this->collectVitals($pid, $sources, $statuses);
        $this->collectLabs($pid, $sources, $statuses);
        $this->collectNotes($pid, $sources, $statuses);

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
        $count = $this->collectActiveIssueSources($pid, 'medical_problem', 'problem', 'problem', $sources, 6);
        $statuses[] = $count === 0
            ? $this->status('problem_list', 'unavailable', 'No active problem-list records found in retrieved lists.')
            : $this->status('problem_list', 'success');
    }

    private function collectAllergies(string $pid, array &$sources, array &$statuses): void
    {
        $count = $this->collectActiveIssueSources($pid, 'allergy', 'allergy', 'allergy', $sources, 6);
        $statuses[] = $count === 0
            ? $this->status('allergies', 'unavailable', 'No active allergy records found in retrieved lists.')
            : $this->status('allergies', 'success');
    }

    private function collectActiveIssueSources(
        string $pid,
        string $type,
        string $recordType,
        string $sourcePrefix,
        array &$sources,
        int $limit
    ): int
    {
        // Match the patient dashboard semantics for active issues:
        // unresolved outcome and blank/future end date.
        $result = sqlStatement(
            "SELECT id, title, begdate, date, enddate, outcome " .
            "FROM lists WHERE pid = ? AND type = ? " .
            "ORDER BY COALESCE(date, begdate) DESC LIMIT 48",
            [$pid, $type]
        );
        $count = 0;
        while ($row = sqlFetchArray($result)) {
            if ($count >= $limit) {
                break;
            }
            if (!$this->isActiveIssueRow($row) || empty($row['title'])) {
                continue;
            }
            $count++;
            $this->addSource(
                $sources,
                $sourcePrefix . '-' . (string)$row['id'],
                $recordType,
                'lists.title',
                (string)$row['title'],
                (string)($row['date'] ?: $row['begdate'] ?: gmdate('c'))
            );
        }
        return $count;
    }

    private function collectMedications(string $pid, array &$sources, array &$statuses): void
    {
        $count = $this->collectActiveIssueSources($pid, 'medication', 'medication', 'medication-list', $sources, 6);
        if ($count === 0) {
            $count = $this->collectActivePrescriptions($pid, $sources, 6);
        }
        $statuses[] = $count === 0
            ? $this->status('medications', 'unavailable', 'No active medications found in retrieved medication lists or prescriptions.')
            : $this->status('medications', 'success');
    }

    private function collectActivePrescriptions(string $pid, array &$sources, int $limit): int
    {
        $result = sqlStatement(
            "SELECT id, drug, date_added, start_date FROM prescriptions WHERE patient_id = ? AND active = 1 " .
            "ORDER BY COALESCE(date_added, start_date) DESC LIMIT ?",
            [$pid, $limit]
        );
        $count = 0;
        while ($row = sqlFetchArray($result)) {
            if (!empty($row['drug'])) {
                $count++;
                $this->addSource(
                    $sources,
                    'medication-rx-' . (string)$row['id'],
                    'medication',
                    'prescriptions.drug',
                    (string)$row['drug'],
                    (string)($row['date_added'] ?: $row['start_date'] ?: gmdate('c'))
                );
            }
        }
        return $count;
    }

    private function collectVitals(string $pid, array &$sources, array &$statuses): void
    {
        $row = sqlQuery(
            "SELECT id, date, bps, bpd, pulse, temperature, weight, height FROM form_vitals WHERE pid = ? ORDER BY date DESC LIMIT 1",
            [$pid]
        );
        if (empty($row)) {
            $statuses[] = $this->status('vitals', 'unavailable', 'No vitals found in retrieved form_vitals records.');
            return;
        }

        foreach (['bps', 'bpd', 'pulse', 'temperature', 'weight', 'height'] as $field) {
            if ($row[$field] !== null && $row[$field] !== '') {
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
        $statuses[] = $this->status('vitals', 'success');
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
            "ORDER BY COALESCE(pr.date, prep.date_report, prep.date_collected, po.date_collected, po.date_ordered) DESC " .
            "LIMIT 8",
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
            "SELECT id, date, body FROM pnotes WHERE pid = ? ORDER BY date DESC LIMIT 2",
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

    private function addSource(
        array &$sources,
        string $id,
        string $recordType,
        string $fieldPath,
        string $value,
        string $recordedAt = '',
        string $noteSpan = ''
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
        $sources[] = $source;
    }

    private function status(string $adapter, string $status, string $reason = ''): array
    {
        return [
            'adapter' => $adapter,
            'status' => $status,
            'reason' => $reason,
        ];
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
}
