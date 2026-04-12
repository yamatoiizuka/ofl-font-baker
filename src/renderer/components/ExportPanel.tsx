/**
 * @fileoverview Export panel component for configuring output family name, weight, file path, and triggering the merge process.
 */

import React, { useState, useEffect } from 'react';
import { useMergeStore } from '@/renderer/stores/mergeStore';
import { useMerge } from '@/renderer/hooks/useMerge';
import { Button } from '@/renderer/components/ui/button';
import { ExportMetadataModal } from '@/renderer/components/ExportMetadataModal';
import { cn } from '@/renderer/lib/utils';
import { WEIGHT_MAP, DONE_DISPLAY_MS, ERROR_DISPLAY_MS } from '@/shared/constants';

/**
 * Export panel component with font family name input, weight selector, progress bar,
 * and export/stop button for the font merge workflow.
 */
export const ExportPanel: React.FC = () => {
  const {
    latinFont,
    baseFont,
    outputFamilyName,
    outputWeight,
    setOutputFamilyName,
    setOutputWeight,
    mergeProgress,
    setMergeProgress,
    setIsMerging,
  } = useMergeStore();
  const { startMerge, isMerging } = useMerge();
  const [isHoveringStop, setIsHoveringStop] = useState(false);
  const [metadataOpen, setMetadataOpen] = useState(false);

  const hasValidName = outputFamilyName.trim().length > 0;
  const canMerge = baseFont && !isMerging && hasValidName;
  const isDone = mergeProgress?.stage === 'done';
  const isError = mergeProgress?.stage === 'error';
  const showProgress = mergeProgress && !isDone;

  // Auto-hide progress after done or error
  useEffect(() => {
    if (!isDone && !isError) return;
    const timer = setTimeout(
      () => setMergeProgress(null),
      isError ? ERROR_DISPLAY_MS : DONE_DISPLAY_MS,
    );
    return () => clearTimeout(timer);
  }, [isDone, isError, setMergeProgress]);

  /**
   * Cancels the ongoing merge process and updates the progress state.
   */
  function handleStop() {
    window.electronAPI.abortMerge();
    setIsMerging(false);
    setMergeProgress({
      stage: 'error',
      percent: 0,
      message: 'Export cancelled',
    });
  }

  return (
    <div className="@container shrink-0 border-t border-border">
      {/* Progress / Done message */}
      {showProgress && (
        <div
          className={cn(
            'px-8 pt-4 pb-2 text-xs',
            isError ? 'text-red-400' : 'text-muted-foreground',
          )}
        >
          {mergeProgress.message.endsWith('...') ? (
            <>
              {mergeProgress.message.slice(0, -3)}
              <span className="dot-1">.</span>
              <span className="dot-2">.</span>
              <span className="dot-3">.</span>
            </>
          ) : (
            mergeProgress.message
          )}
        </div>
      )}
      {isDone && (
        <div className="px-8 pt-4 pb-2 flex items-center gap-1.5">
          <svg width="14" height="14" viewBox="0 0 16 16" className="text-green-500 shrink-0">
            <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeWidth="1.2" fill="none" />
            <path
              d="M5 8 L7 10 L11 6"
              stroke="currentColor"
              strokeWidth="1.4"
              fill="none"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <span className="text-xs text-foreground">
            Export complete
            {(() => {
              const en = latinFont?.glyphCount ?? 0;
              const jp = baseFont?.glyphCount ?? 0;
              const count = (jp + en - Math.min(en, jp) * 0.3) | 0;
              const upm = baseFont?.unitsPerEm ?? latinFont?.unitsPerEm ?? 0;
              return count > 0 ? ` · ${count} Glyphs · UPM ${upm}` : '';
            })()}
          </span>
        </div>
      )}

      <div
        className={cn('flex items-end gap-3 px-8 pb-8', showProgress || isDone ? 'pt-2' : 'pt-6')}
      >
        {/* Font Family */}
        <div className="flex-1 min-w-24">
          <label
            className={cn(
              'text-[11px] block mb-1',
              hasValidName ? 'text-muted-foreground' : 'text-red-400',
            )}
          >
            {hasValidName ? 'Font Family' : 'Font Family is Required'}
          </label>
          <input
            type="text"
            value={outputFamilyName}
            onChange={(e) => setOutputFamilyName(e.target.value)}
            onBlur={() => useMergeStore.getState().pushHistory()}
            disabled={isMerging}
            className="w-full px-3 py-2 rounded-md border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-ring placeholder:text-foreground/40 disabled:opacity-50 disabled:cursor-not-allowed"
          />
        </div>

        {/* Weight */}
        <WeightSelect value={outputWeight} onChange={setOutputWeight} disabled={isMerging} />

        {/* Metadata... */}
        <Button
          variant="ghost"
          size="sm"
          disabled={!baseFont}
          onClick={() => setMetadataOpen(true)}
          className="text-xs text-muted-foreground hover:text-foreground h-[38px] px-3 shrink-0"
        >
          Metadata...
        </Button>

        {isMerging ? (
          <Button
            onClick={handleStop}
            onMouseEnter={() => setIsHoveringStop(true)}
            onMouseLeave={() => setIsHoveringStop(false)}
            size="lg"
            variant="secondary"
            className={cn(
              'rounded-md w-[100px] @[36rem]:w-[130px] h-[38px] shrink-0 text-base transition-none',
              isHoveringStop && 'text-red-500',
            )}
          >
            {isHoveringStop ? (
              'Stop'
            ) : (
              <svg
                className="animate-spin h-5 w-5 text-muted-foreground"
                viewBox="0 0 24 24"
                fill="none"
              >
                <circle
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeDasharray="50 14"
                />
              </svg>
            )}
          </Button>
        ) : (
          <Button
            onClick={startMerge}
            disabled={!canMerge}
            size="lg"
            className="rounded-md w-[100px] @[36rem]:w-[130px] h-[38px] shrink-0 text-base"
          >
            Export
          </Button>
        )}

        <ExportMetadataModal open={metadataOpen} onOpenChange={setMetadataOpen} />
      </div>
    </div>
  );
};

/**
 * A custom dropdown selector for font weight values (100-900).
 */

function WeightSelect({
  value,
  onChange,
  disabled = false,
}: {
  value: number;
  onChange: (v: number) => void;
  disabled?: boolean;
}) {
  const selectClass = cn(
    'w-full px-3 py-2 rounded-md border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-ring appearance-none',
    disabled && 'opacity-50 cursor-not-allowed',
  );
  const selectStyle = {
    backgroundImage:
      "url(\"data:image/svg+xml,%3Csvg width='10' height='6' viewBox='0 0 10 6' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M1 1L5 5L9 1' stroke='%23999' stroke-width='1.2' stroke-linecap='round'/%3E%3C/svg%3E\")",
    backgroundRepeat: 'no-repeat',
    backgroundPosition: 'right 12px center',
  };

  return (
    <div className="w-[6.5rem] @[36rem]:w-36 shrink-0">
      <label className="text-[11px] block mb-1 text-muted-foreground">Weight</label>
      {/* Narrow: name only */}
      <select
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        disabled={disabled}
        className={cn(selectClass, '@[36rem]:hidden')}
        style={selectStyle}
      >
        {WEIGHT_MAP.map((w) => (
          <option key={w.value} value={w.value}>
            {w.name}
          </option>
        ))}
      </select>
      {/* Wide: full label */}
      <select
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        disabled={disabled}
        className={cn(selectClass, 'hidden @[36rem]:block')}
        style={selectStyle}
      >
        {WEIGHT_MAP.map((w) => (
          <option key={w.value} value={w.value}>
            {w.label}
          </option>
        ))}
      </select>
    </div>
  );
}
