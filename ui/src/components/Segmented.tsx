import { LayoutGroup } from "motion/react";
import * as m from "motion/react-m";
import { useId } from "react";

export interface Segment<V extends string> {
  value: V;
  label: string;
  count?: number;
}

/** A segmented control: a track with one raised thumb that slides (DESIGN.md). */
export function Segmented<V extends string>({
  segments,
  value,
  onChange,
  label,
}: {
  segments: Segment<V>[];
  value: V;
  onChange: (value: V) => void;
  label: string;
}) {
  const id = useId();
  return (
    <LayoutGroup id={id}>
      <fieldset className="segmented" aria-label={label}>
        {segments.map((segment) => (
          <button
            key={segment.value}
            type="button"
            aria-pressed={segment.value === value}
            onClick={() => onChange(segment.value)}
          >
            {segment.value === value && <m.span layoutId="thumb" className="thumb" />}
            <span>{segment.label}</span>
            {segment.count !== undefined && <span className="seg-count">{segment.count}</span>}
          </button>
        ))}
      </fieldset>
    </LayoutGroup>
  );
}
