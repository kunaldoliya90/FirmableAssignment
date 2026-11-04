// Horizontal bar list for categorical distributions
import { formatNumber } from "@/lib/format";

export function BarList({ data, format = formatNumber, max }: { data: Record<string, number>; format?: (v: number) => string; max?: number }) {
  const rows = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const top = max ?? Math.max(1, ...rows.map(([, v]) => v));
  return (
    <ul className="space-y-1.5">
      {rows.map(([label, value]) => (
        <li key={label} className="grid grid-cols-[minmax(0,10rem)_1fr_4.5rem] items-center gap-3 text-sm">
          <span className="truncate text-slate-600" title={label}>
            {label}
          </span>
          <span className="h-2 rounded-full bg-slate-100">
            <span className="block h-2 rounded-full bg-brand-500" style={{ width: `${(value / top) * 100}%` }} />
          </span>
          <span className="text-right tabular-nums text-slate-700">{format(value)}</span>
        </li>
      ))}
    </ul>
  );
}
