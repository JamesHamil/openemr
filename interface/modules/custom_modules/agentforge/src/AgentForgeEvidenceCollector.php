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
        $this->collectLists($pid, 'medical_problem', 'problem_list', 'problem', $sources, $statuses);
    }

    private function collectAllergies(string $pid, array &$sources, array &$statuses): void
    {
        $this->collectLists($pid, 'allergy', 'allergies', 'allergy', $sources, $statuses);
    }

    private function collectLists(string $pid, string $type, string $adapter, string $recordType, array &$sources, array &$statuses): void
    {
        $result = sqlStatement(
            "SELECT id, title, begdate, date FROM lists WHERE pid = ? AND type = ? AND activity = 1 ORDER BY COALESCE(date, begdate) DESC LIMIT 8",
            [$pid, $type]
        );
        $count = 0;
        while ($row = sqlFetchArray($result)) {
            if (!empty($row['title'])) {
                $count++;
                $this->addSource(
                    $sources,
                    $recordType . '-' . (string)$row['id'],
                    $recordType,
                    'lists.title',
                    (string)$row['title'],
                    (string)($row['date'] ?: $row['begdate'] ?: gmdate('c'))
                );
            }
        }
        $statuses[] = $count === 0
            ? $this->status($adapter, 'unavailable', 'No active records found in retrieved lists.')
            : $this->status($adapter, 'success');
    }

    private function collectMedications(string $pid, array &$sources, array &$statuses): void
    {
        $result = sqlStatement(
            "SELECT id, drug, date_added, start_date FROM prescriptions WHERE patient_id = ? AND active = 1 ORDER BY COALESCE(date_added, start_date) DESC LIMIT 8",
            [$pid]
        );
        $count = 0;
        while ($row = sqlFetchArray($result)) {
            if (!empty($row['drug'])) {
                $count++;
                $this->addSource(
                    $sources,
                    'medication-' . (string)$row['id'],
                    'medication',
                    'prescriptions.drug',
                    (string)$row['drug'],
                    (string)($row['date_added'] ?: $row['start_date'] ?: gmdate('c'))
                );
            }
        }
        $statuses[] = $count === 0
            ? $this->status('medications', 'unavailable', 'No active medications found in retrieved prescriptions.')
            : $this->status('medications', 'success');
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

    private function collectNotes(string $pid, array &$sources, array &$statuses): void
    {
        $result = sqlStatement(
            "SELECT id, date, body FROM pnotes WHERE pid = ? ORDER BY date DESC LIMIT 5",
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
}
