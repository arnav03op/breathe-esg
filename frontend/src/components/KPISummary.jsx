import { useEffect, useState } from 'react';
import { fetchSummary } from '../api';

function formatCO2(value) {
  if (value == null) return '—';
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toFixed(1);
}

const CARDS = [
  {
    key: 'total_co2e_kg',
    label: 'Total Calculated CO₂e',
    unit: 'kgCO₂e',
    icon: (
      <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v2.25m6.364.386-1.591 1.591M21 12h-2.25m-.386 6.364-1.591-1.591M12 18.75V21m-4.773-4.227-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0Z" />
      </svg>
    ),
    color: 'brand',
    getValue: (d) => formatCO2(d.total_co2e_kg),
  },
  {
    key: 'pending',
    label: 'Rows Pending Review',
    unit: 'rows',
    icon: (
      <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
      </svg>
    ),
    color: 'amber',
    getValue: (d) => d.by_status?.PENDING ?? 0,
  },
  {
    key: 'flagged',
    label: 'Rows Flagged for Errors',
    unit: 'rows',
    icon: (
      <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
      </svg>
    ),
    color: 'danger',
    getValue: (d) => d.by_status?.FLAGGED ?? 0,
  },
];

const colorMap = {
  brand: {
    bg: 'bg-brand-500/10',
    border: 'border-brand-500/20',
    icon: 'text-brand-400',
    value: 'text-brand-400',
  },
  amber: {
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/20',
    icon: 'text-amber-400',
    value: 'text-amber-400',
  },
  danger: {
    bg: 'bg-danger-500/10',
    border: 'border-danger-500/20',
    icon: 'text-danger-400',
    value: 'text-danger-400',
  },
};

export default function KPISummary({ refreshKey }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetchSummary()
      .then(setData)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [refreshKey]);

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      {CARDS.map((card, i) => {
        const c = colorMap[card.color];
        return (
          <div
            key={card.key}
            className={`animate-fade-in rounded-xl border ${c.border} ${c.bg} p-5 transition-all hover:scale-[1.02]`}
            style={{ animationDelay: `${i * 80}ms` }}
          >
            <div className="flex items-start justify-between">
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-slate-400">
                  {card.label}
                </p>
                <p className={`mt-2 text-3xl font-extrabold tracking-tight ${c.value}`}>
                  {loading ? (
                    <span className="animate-pulse-soft">···</span>
                  ) : (
                    data ? card.getValue(data) : '—'
                  )}
                </p>
                <p className="mt-1 text-xs text-slate-500">{card.unit}</p>
              </div>
              <div className={`rounded-lg p-2 ${c.bg} ${c.icon}`}>
                {card.icon}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
