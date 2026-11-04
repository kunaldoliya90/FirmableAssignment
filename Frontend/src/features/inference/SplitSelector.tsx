// Checkbox group for choosing dataset splits
"use client";

const SPLITS = ["train", "validation", "test", "challenge"] as const;

export function SplitSelector({ value, onChange }: { value: string[]; onChange: (splits: string[]) => void }) {
  return (
    <div className="flex flex-wrap gap-3 text-sm">
      {SPLITS.map((split) => (
        <label key={split} className="flex items-center gap-1.5">
          <input
            type="checkbox"
            checked={value.includes(split)}
            onChange={(e) => onChange(e.target.checked ? [...value, split] : value.filter((s) => s !== split))}
          />
          {split}
        </label>
      ))}
    </div>
  );
}
