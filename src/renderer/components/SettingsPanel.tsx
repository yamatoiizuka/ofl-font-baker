/**
 * @fileoverview Settings panel component for adjusting font-specific parameters such as baseline, scale, and variable axes.
 */

import React, { useState, useRef } from 'react';
import { FontSource } from '@/shared/types';
import { useMergeStore } from '@/renderer/stores/mergeStore';

interface Props {
  font: FontSource;
  role: 'latin' | 'base';
  onUpdateBaseline: (value: number) => void;
  onUpdateScale: (value: number) => void;
  onUpdateAxis: (tag: string, value: number) => void;
}

/**
 * Displays geometry and variable axis controls for a selected font source.
 */
export const SettingsPanel: React.FC<Props> = ({
  font,
  role,
  onUpdateBaseline,
  onUpdateScale,
  onUpdateAxis,
}) => {
  const scalePercent = Math.round(font.scale * 100);

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Header: font info */}
      <div className="pb-10 w-full">
        <div className="flex items-center gap-2 w-full">
          <h2 className="text-lg font-medium">{font.familyName}</h2>
          {font.isVariable && (
            <span className="text-[13px] border rounded-full px-[8px] py-[2px] tracking-[0.02em] shrink-0 leading-[1]">
              Variable
            </span>
          )}
        </div>
        <div className="text-xs text-muted-foreground mt-1 w-full">
          {font.styleName && !(font.isVariable && font.axes.some((a) => a.tag === 'wght')) && (
            <>{font.styleName.split(' \u00b7 ')[0]} · </>
          )}
          UPM {font.unitsPerEm.toLocaleString()} · {font.glyphCount.toLocaleString()} Glyphs
        </div>
      </div>

      {/* Scrollable controls */}
      <div className="flex-1 overflow-y-auto space-y-11 w-full">
        {/* Geometry */}
        <section className="w-full">
          <h3 className="text-sm font-medium mb-7">Geometry</h3>
          <div className="space-y-5">
            <SliderWithInput
              label="Baseline"
              value={font.baselineOffset}
              onChange={onUpdateBaseline}
              min={-200}
              max={200}
              step={1}
            />
            <SliderWithInput
              label="Scale"
              value={scalePercent}
              onChange={(v) => onUpdateScale(v / 100)}
              min={50}
              max={150}
              step={1}
              suffix="%"
            />
          </div>
        </section>

        {/* Variable Axis */}
        {font.isVariable && font.axes.length > 0 && (
          <section className="w-full">
            <h3 className="text-sm font-medium mb-7">Variable Axis</h3>
            <div className="space-y-5">
              {font.axes.map((axis) => (
                <SliderWithInput
                  key={axis.tag}
                  label={axis.name}
                  tag={axis.tag}
                  value={axis.currentValue}
                  onChange={(v) => onUpdateAxis(axis.tag, v)}
                  min={axis.minValue}
                  max={axis.maxValue}
                  step={axis.maxValue - axis.minValue > 10 ? 1 : 0.1}
                />
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
};

/**
 * A slider input component with an inline editable numeric value display.
 * Supports range constraints, step increments, and an optional suffix.
 */
function SliderWithInput({
  label,
  tag,
  value,
  onChange,
  min,
  max,
  step,
  suffix,
}: {
  label: string;
  tag?: string;
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step: number;
  suffix?: string;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  /**
   * Enters inline editing mode for the numeric value display.
   */
  function startEdit() {
    setEditValue(String(Number.isInteger(value) ? value : Number(value.toFixed(1))));
    setIsEditing(true);
    setTimeout(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    }, 0);
  }

  /**
   * Commits the edited value, clamping it to the min/max range.
   */
  function commitEdit() {
    const num = Number(editValue);
    if (!isNaN(num)) {
      onChange(Math.min(max, Math.max(min, num)));
    }
    setIsEditing(false);
    useMergeStore.getState().pushHistory();
  }

  const display = Number.isInteger(value) ? String(value) : value.toFixed(1);

  /**
   * Commits the current edit and moves focus to the prev/next slider's value field.
   * Wraps around the end of the list so Tab cycling stays within the panel.
   */
  function focusSibling(direction: 1 | -1) {
    const currentRow = inputRef.current?.closest('.slider-row');
    commitEdit();
    // After commit, the input is replaced by the span on the next render;
    // rAF lets that re-render happen before we click the target span.
    requestAnimationFrame(() => {
      const rows = Array.from(document.querySelectorAll('.slider-row'));
      const idx = currentRow ? rows.indexOf(currentRow as Element) : -1;
      if (idx === -1 || rows.length === 0) return;
      const nextIdx = (idx + direction + rows.length) % rows.length;
      (rows[nextIdx].querySelector('.slider-value') as HTMLElement | null)?.click();
    });
  }

  return (
    <div className="slider-row">
      <div className="flex justify-between">
        <label className="text-sm text-foreground">
          {label}
          {tag && (
            <span className="text-[11px] text-muted-foreground/70 ml-2 font-mono">{tag}</span>
          )}
        </label>
        {isEditing ? (
          <input
            ref={inputRef}
            type="number"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onBlur={commitEdit}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitEdit();
              else if (e.key === 'Escape') setIsEditing(false);
              else if (e.key === 'Tab') {
                e.preventDefault();
                focusSibling(e.shiftKey ? -1 : 1);
              }
            }}
            min={min}
            max={max}
            step={step}
            className="w-16 text-sm font-mono tabular-nums text-right bg-secondary/60 rounded-md px-1.5 py-0.5 outline-none border-none"
          />
        ) : (
          <span
            className="slider-value text-sm font-mono tabular-nums cursor-pointer hover:text-foreground/70"
            onClick={startEdit}
          >
            {display}
            {suffix ?? ''}
          </span>
        )}
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        onMouseUp={() => useMergeStore.getState().pushHistory()}
        onTouchEnd={() => useMergeStore.getState().pushHistory()}
        className="w-full"
      />
    </div>
  );
}
