// Reliability diagram: accuracy per confidence bin
import type { ReliabilityBin } from "@/lib/api/types";

export function ReliabilityChart({ bins }: { bins: ReliabilityBin[] }) {
  const size = 260;
  const pad = 32;
  const inner = size - pad * 2;
  const scale = (v: number) => pad + v * inner;
  const flip = (v: number) => size - pad - v * inner;
  const filled = bins.filter((b) => b.count > 0 && b.accuracy !== undefined);
  const maxCount = Math.max(1, ...filled.map((b) => b.count));
  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="w-full max-w-sm" role="img" aria-label="Reliability diagram">
      <rect x={pad} y={pad} width={inner} height={inner} fill="#f8fafc" stroke="#e2e8f0" />
      <line x1={scale(0)} y1={flip(0)} x2={scale(1)} y2={flip(1)} stroke="#94a3b8" strokeDasharray="4 4" />
      {filled.map((b) => {
        const width = (b.bin[1] - b.bin[0]) * inner;
        const height = (b.accuracy ?? 0) * inner;
        return (
          <g key={b.bin[0]}>
            <rect
              x={scale(b.bin[0]) + 1}
              y={flip(b.accuracy ?? 0)}
              width={width - 2}
              height={height}
              fill="#3b6ff5"
              opacity={0.35 + 0.65 * (b.count / maxCount)}
            >
              <title>
                {`confidence ${b.bin[0]}–${b.bin[1]}: accuracy ${((b.accuracy ?? 0) * 100).toFixed(1)}% over ${b.count} predictions`}
              </title>
            </rect>
          </g>
        );
      })}
      {[0, 0.5, 1].map((t) => (
        <g key={t} className="text-[9px]" fill="#64748b">
          <text x={scale(t)} y={size - pad + 14} textAnchor="middle">
            {t}
          </text>
          <text x={pad - 6} y={flip(t) + 3} textAnchor="end">
            {t}
          </text>
        </g>
      ))}
      <text x={size / 2} y={size - 4} textAnchor="middle" className="text-[10px]" fill="#475569">
        confidence
      </text>
      <text x={10} y={size / 2} textAnchor="middle" className="text-[10px]" fill="#475569" transform={`rotate(-90 10 ${size / 2})`}>
        accuracy
      </text>
    </svg>
  );
}
