"use client";

export interface PickerRow {
  key: string;
  label: string;
}

interface SkillPickerProps {
  listId: string;
  rows: PickerRow[];
  activeIndex: number;
  onPick: (key: string) => void;
}

export function optionId(listId: string, index: number): string {
  return `${listId}-opt-${index}`;
}

/** The "/" listbox shown above the chat input. Text only, no markup from skills. */
export default function SkillPicker({ listId, rows, activeIndex, onPick }: SkillPickerProps) {
  return (
    <ul
      id={listId}
      role="listbox"
      aria-label="Skills"
      className="absolute bottom-full left-0 right-0 mb-2 max-h-64 overflow-y-auto rounded-lg border border-gray-200 bg-white shadow-lg z-10"
    >
      {rows.map((row, i) => (
        <li
          key={row.key}
          id={optionId(listId, i)}
          role="option"
          aria-selected={i === activeIndex}
          // mouse-down keeps the textarea focused
          onMouseDown={(e) => {
            e.preventDefault();
            onPick(row.key);
          }}
          className={`cursor-pointer px-4 py-2 text-sm ${
            i === activeIndex ? "bg-blue-50 text-blue-900" : "text-gray-700 hover:bg-gray-50"
          }`}
        >
          {row.label}
        </li>
      ))}
    </ul>
  );
}
