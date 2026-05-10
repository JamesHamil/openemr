import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ClinicalCopilot, ClinicalCopilotConfig } from './ClinicalCopilot';

describe('clinical co-pilot', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the modern prompt workspace', () => {
    render(<ClinicalCopilot config={config()} />);

    expect(screen.getByRole('heading', { name: 'Clinical Co-Pilot' })).toBeInTheDocument();
    expect(screen.getByLabelText('Question')).toHaveValue('Give me a chart brief for rounds.');
    expect(screen.getByRole('button', { name: 'Generate Brief' })).toBeInTheDocument();
    expect(screen.getByText('The verified response will appear here.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Sources' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Warnings' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Trace' })).toBeInTheDocument();
  });

  it('shows patient context warning without an active patient', () => {
    render(<ClinicalCopilot config={{ ...config(), patientId: '' }} />);

    expect(screen.getByText('Open a patient chart')).toBeInTheDocument();
  });

  it('shows answer citations linked to source cards', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      answer: 'Prednisone is prescribed twice daily.',
      verification_status: 'verified',
      claims: [
        {
          id: 'claim-1',
          text: 'Prednisone frequency is 2 daily.',
          source_ids: ['medication-list-163', 'document-fact-756'],
        },
      ],
      sources: [
        {
          id: 'medication-list-163',
          record_type: 'medication',
          extracted_value: 'prednisone; instructions frequency: 2 daily',
          field_path: 'lists.title',
        },
        {
          id: 'document-fact-756',
          record_type: 'document_fact',
          extracted_value: 'prednisone; dose: 20 mg; frequency: 2 daily',
          metadata: {
            openemr_document_id: '328',
            source_kind: 'document_extraction',
          },
        },
      ],
    }), {
      headers: { 'Content-Type': 'application/json' },
    })));

    render(<ClinicalCopilot config={config()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Generate Brief' }));

    await waitFor(() => {
      expect(screen.getByText('Prednisone is prescribed twice daily.')).toBeInTheDocument();
    });
    expect(screen.getByRole('link', { name: '[medication-list-163]' })).toHaveAttribute('href', '#af-source-medication-list-163');
    expect(screen.getByRole('link', { name: '[document-fact-756]' })).toHaveAttribute('href', '#af-source-document-fact-756');
  });
});

function config(): ClinicalCopilotConfig {
  return {
    authorized: true,
    patientId: '3',
    encounterId: '',
    csrfToken: 'csrf',
    chatUrl: 'chat.php',
    documentBaseUrl: '/controller.php',
  };
}
