/**
 * Centralised API helper.
 * All calls go through the Vite proxy → Django backend at /api/...
 */

const BASE = '/api';

async function request(path, options = {}) {
  const url = `${BASE}${path}`;
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `API ${res.status}: ${res.statusText}`);
  }
  return res.json();
}

/* ── Emissions ── */
export const fetchEmissions = (params = '') =>
  request(`/emissions/?format=json&${params}`);

export const fetchSummary = () =>
  request('/emissions/summary/?format=json');

export const approveRow = (id) =>
  request(`/emissions/${id}/approve/`, { method: 'POST' });

export const flagRow = (id, note) =>
  request(`/emissions/${id}/flag/`, {
    method: 'POST',
    body: JSON.stringify({ note }),
  });

export const bulkApprove = (ids, note = 'Bulk approval from dashboard') =>
  request('/emissions/bulk-approve/', {
    method: 'POST',
    body: JSON.stringify({ ids, note }),
  });

export const fetchRowDetail = (id) =>
  request(`/emissions/${id}/?format=json`);

export const fetchRowHistory = (id) =>
  request(`/emissions/${id}/history/?format=json`);

/* ── Ingestion logs ── */
export const fetchIngestionLogs = () =>
  request('/ingestion-logs/?format=json');

/* ── File uploads ── */
export async function uploadFile(sourceType, file, companyId) {
  const form = new FormData();
  form.append('file', file);
  form.append('company_id', companyId);

  const res = await fetch(`${BASE}/upload/${sourceType}/`, {
    method: 'POST',
    body: form,
    // Don't set Content-Type — browser sets multipart boundary automatically
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `Upload failed: ${res.status}`);
  }
  return res.json();
}
