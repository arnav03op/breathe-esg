import { useState } from 'react';
import { uploadFile } from '../api';

const SOURCES = [
  { key: 'sap', label: 'SAP Export', accept: '.csv', desc: 'Fuel & procurement CSV' },
  { key: 'utility', label: 'Utility Export', accept: '.csv', desc: 'Electricity billing CSV' },
  { key: 'travel', label: 'Travel Export', accept: '.json', desc: 'Corporate travel JSON' },
];

export default function UploadPanel({ open, onClose, onSuccess }) {
  const [uploading, setUploading] = useState({});
  const [results, setResults] = useState({});
  const [errors, setErrors] = useState({});

  if (!open) return null;

  async function handleUpload(sourceKey, file) {
    setUploading((u) => ({ ...u, [sourceKey]: true }));
    setErrors((e) => ({ ...e, [sourceKey]: null }));
    setResults((r) => ({ ...r, [sourceKey]: null }));

    try {
      // Using company_id=1 (Acme Corp) as default for prototype
      const result = await uploadFile(sourceKey, file, 1);
      setResults((r) => ({ ...r, [sourceKey]: result }));
      onSuccess?.();
    } catch (err) {
      setErrors((e) => ({ ...e, [sourceKey]: err.message }));
    } finally {
      setUploading((u) => ({ ...u, [sourceKey]: false }));
    }
  }

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm transition-opacity"
        onClick={onClose}
      />

      {/* Slide-over panel */}
      <div className="animate-slide-in fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col border-l border-slate-700/60 bg-slate-900 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-700/60 px-6 py-4">
          <div>
            <h2 className="text-lg font-bold text-white">Upload Data Sources</h2>
            <p className="text-xs text-slate-400">Select a file for each source type</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-slate-800 hover:text-white"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Upload zones */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {SOURCES.map((src) => (
            <UploadZone
              key={src.key}
              source={src}
              loading={uploading[src.key]}
              result={results[src.key]}
              error={errors[src.key]}
              onUpload={(file) => handleUpload(src.key, file)}
            />
          ))}
        </div>
      </div>
    </>
  );
}

function UploadZone({ source, loading, result, error, onUpload }) {
  const [dragOver, setDragOver] = useState(false);

  function handleDrop(e) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) onUpload(file);
  }

  function handleChange(e) {
    const file = e.target.files[0];
    if (file) onUpload(file);
    e.target.value = '';
  }

  const borderColor = result
    ? 'border-brand-500/40 bg-brand-500/5'
    : error
      ? 'border-danger-500/40 bg-danger-500/5'
      : dragOver
        ? 'border-brand-400/60 bg-brand-500/10'
        : 'border-slate-700/60 bg-slate-800/50';

  return (
    <div
      className={`group relative rounded-xl border-2 border-dashed ${borderColor} p-5 transition-all`}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      <div className="flex items-start gap-4">
        <div className="rounded-lg bg-slate-700/50 p-2.5 text-slate-300">
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m6.75 12-3-3m0 0-3 3m3-3v6m-1.5-15H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
          </svg>
        </div>
        <div className="flex-1">
          <p className="font-semibold text-white">{source.label}</p>
          <p className="text-xs text-slate-400">{source.desc}</p>

          {loading && (
            <p className="mt-2 text-xs text-brand-400 animate-pulse-soft">
              Uploading & processing…
            </p>
          )}
          {result && (
            <p className="mt-2 text-xs text-brand-400">
              ✓ {result.created} rows created, {result.flagged} flagged
            </p>
          )}
          {error && (
            <p className="mt-2 text-xs text-danger-400">✗ {error}</p>
          )}

          {!loading && (
            <label className="mt-3 inline-flex cursor-pointer items-center gap-1.5 rounded-lg bg-slate-700/60 px-3 py-1.5 text-xs font-medium text-slate-300 transition-colors hover:bg-slate-600/60 hover:text-white">
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              Choose file ({source.accept})
              <input
                type="file"
                accept={source.accept}
                className="hidden"
                onChange={handleChange}
              />
            </label>
          )}
        </div>
      </div>
    </div>
  );
}
