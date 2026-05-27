import { useEffect, useState } from 'react';
import { approveRow, bulkApprove, fetchEmissions } from '../api';

function classNames(...classes) {
  return classes.filter(Boolean).join(' ');
}

export default function ReviewTable({ refreshKey, onRefresh }) {
  const [data, setData] = useState({ results: [], count: 0 });
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('PENDING'); // PENDING or FLAGGED
  const [actionLoading, setActionLoading] = useState(null);

  useEffect(() => {
    loadData();
  }, [refreshKey, filter]);

  async function loadData() {
    setLoading(true);
    try {
      const res = await fetchEmissions(`status=${filter}`);
      setData(res);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  async function handleApprove(id) {
    setActionLoading(id);
    try {
      await approveRow(id);
      // Optimistic UI update: remove from list
      setData((prev) => ({
        ...prev,
        count: prev.count - 1,
        results: prev.results.filter((row) => row.id !== id),
      }));
      onRefresh(); // Refresh KPI cards
    } catch (err) {
      alert(`Failed to approve: ${err.message}`);
    } finally {
      setActionLoading(null);
    }
  }

  async function handleBulkApprove() {
    if (!confirm('Approve all currently visible clean (PENDING) rows?')) return;
    
    setActionLoading('bulk');
    // Gather all PENDING rows currently fetched
    const ids = data.results.filter(r => r.status === 'PENDING').map(r => r.id);
    
    if (ids.length === 0) {
      alert('No clean rows to approve.');
      setActionLoading(null);
      return;
    }

    try {
      await bulkApprove(ids);
      loadData();
      onRefresh();
    } catch (err) {
      alert(`Bulk approve failed: ${err.message}`);
    } finally {
      setActionLoading(null);
    }
  }

  return (
    <div className="mt-8 flex flex-col gap-4 animate-slide-in">
      {/* Table Header & Controls */}
      <div className="flex items-center justify-between">
        <div className="flex gap-2 rounded-lg bg-slate-800/50 p-1">
          <button
            onClick={() => setFilter('PENDING')}
            className={classNames(
              'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
              filter === 'PENDING'
                ? 'bg-slate-700 text-white shadow-sm'
                : 'text-slate-400 hover:text-white'
            )}
          >
            Pending Review
          </button>
          <button
            onClick={() => setFilter('FLAGGED')}
            className={classNames(
              'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
              filter === 'FLAGGED'
                ? 'bg-danger-500/20 text-danger-400 shadow-sm'
                : 'text-slate-400 hover:text-white'
            )}
          >
            Flagged Errors
          </button>
        </div>

        {filter === 'PENDING' && (
          <button
            onClick={handleBulkApprove}
            disabled={actionLoading === 'bulk' || data.results.length === 0}
            className="flex items-center gap-2 rounded-lg bg-slate-800 px-4 py-2 text-sm font-semibold text-white transition-all hover:bg-slate-700 disabled:opacity-50"
          >
            {actionLoading === 'bulk' ? (
              <span className="animate-pulse">Approving...</span>
            ) : (
              <>
                <svg className="h-4 w-4 text-brand-400" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
                </svg>
                Bulk Approve Clean Rows
              </>
            )}
          </button>
        )}
      </div>

      {/* Table Container */}
      <div className="overflow-hidden rounded-xl border border-slate-700/60 bg-slate-900 shadow-xl">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm text-slate-300">
            <thead className="bg-slate-800/50 text-xs uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-6 py-4 font-medium">Source / Scope</th>
                <th className="px-6 py-4 font-medium">Facility / Category</th>
                <th className="px-6 py-4 font-medium">Dates</th>
                <th className="px-6 py-4 font-medium text-right">Consumption</th>
                <th className="px-6 py-4 font-medium text-right">CO₂e (kg)</th>
                <th className="px-6 py-4 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/50">
              {loading ? (
                <tr>
                  <td colSpan="6" className="px-6 py-12 text-center text-slate-500">
                    <span className="animate-pulse-soft">Loading data...</span>
                  </td>
                </tr>
              ) : data.results.length === 0 ? (
                <tr>
                  <td colSpan="6" className="px-6 py-12 text-center text-slate-500">
                    No {filter.toLowerCase()} rows found.
                  </td>
                </tr>
              ) : (
                data.results.map((row) => (
                  <tr
                    key={row.id}
                    className={classNames(
                      'transition-colors hover:bg-slate-800/50',
                      row.status === 'FLAGGED' ? 'bg-danger-500/5' : ''
                    )}
                  >
                    <td className="px-6 py-4 align-top">
                      <div className="font-medium text-white">{row.source_type}</div>
                      <div className="mt-0.5 text-xs text-slate-500">{row.scope_category_display}</div>
                    </td>
                    <td className="px-6 py-4 align-top">
                      <div className="font-medium text-white truncate max-w-[200px]" title={row.facility_name}>
                        {row.facility_name || '—'}
                      </div>
                      <div className="mt-0.5 text-xs text-slate-500">{row.sub_category}</div>
                      
                      {/* Crucial Error Display */}
                      {row.status === 'FLAGGED' && row.error_notes && (
                        <div className="mt-2 rounded bg-danger-500/10 px-2 py-1.5 border border-danger-500/20 text-xs text-danger-400">
                          <span className="font-semibold uppercase tracking-wider text-[10px] opacity-80 block mb-0.5">Error Detail:</span>
                          {row.error_notes}
                        </div>
                      )}
                    </td>
                    <td className="px-6 py-4 align-top text-slate-400 whitespace-nowrap">
                      {row.activity_start_date ? (
                        <>
                          <div>{row.activity_start_date}</div>
                          {row.activity_end_date && row.activity_end_date !== row.activity_start_date && (
                            <div className="text-xs text-slate-500">to {row.activity_end_date}</div>
                          )}
                        </>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="px-6 py-4 align-top text-right whitespace-nowrap">
                      {row.normalized_value != null ? (
                        <>
                          <div className="font-medium text-slate-200">
                            {row.normalized_value.toLocaleString(undefined, { maximumFractionDigits: 1 })}
                          </div>
                          <div className="mt-0.5 text-xs text-slate-500">{row.normalized_unit}</div>
                        </>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="px-6 py-4 align-top text-right">
                      <div className="font-semibold text-white">
                        {row.co2e_kg != null ? row.co2e_kg.toLocaleString(undefined, { maximumFractionDigits: 2 }) : '—'}
                      </div>
                    </td>
                    <td className="px-6 py-4 align-top text-right">
                      {row.status === 'PENDING' ? (
                        <button
                          onClick={() => handleApprove(row.id)}
                          disabled={actionLoading === row.id}
                          className="inline-flex items-center gap-1.5 rounded bg-brand-500/10 px-3 py-1.5 text-xs font-semibold text-brand-400 transition-colors hover:bg-brand-500/20 disabled:opacity-50"
                        >
                          {actionLoading === row.id ? 'Saving...' : 'Approve'}
                        </button>
                      ) : (
                        <span className="text-xs text-slate-500">Requires Review</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
