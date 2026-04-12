import React from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/renderer/components/ui/dialog';
import { WEIGHT_MAP, WIDTH_MAP, computeStyleName } from '@/shared/constants';
import { useMergeStore } from '@/renderer/stores/mergeStore';
import { cn } from '@/renderer/lib/utils';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface SourceMeta {
  copyright: string;
  designer: string;
  familyName: string;
}

const OFL_LICENSE_TEXT =
  'This Font Software is licensed under the SIL Open Font License, ' +
  'Version 1.1. This license is available with a FAQ at: ' +
  'https://openfontlicense.org';

const OFL_LICENSE_URL = 'https://openfontlicense.org';


/* ------------------------------------------------------------------ */
/*  Shared UI                                                         */
/* ------------------------------------------------------------------ */

const inputClass =
  'w-full px-3 py-1.5 rounded-md border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-ring';

const selectClassName = `${inputClass} appearance-none pr-8`;
const selectArrowStyle = {
  backgroundImage: 'url("data:image/svg+xml,%3Csvg width=\'10\' height=\'6\' viewBox=\'0 0 10 6\' fill=\'none\' xmlns=\'http://www.w3.org/2000/svg\'%3E%3Cpath d=\'M1 1L5 5L9 1\' stroke=\'%23999\' stroke-width=\'1.2\' stroke-linecap=\'round\'/%3E%3C/svg%3E")',
  backgroundRepeat: 'no-repeat',
  backgroundPosition: 'right 12px center',
  backgroundSize: '10px 6px',
} as React.CSSProperties;

const InfoRow: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => {
  if (value === '' || value === null || value === undefined) return null;
  return (
    <div className="flex gap-[18px] py-[2px] text-[14px] pl-2">
      <span className="text-muted-foreground/70 shrink-0 w-[90px] text-right">{label}</span>
      <span className="text-foreground min-w-0 break-words">{value}</span>
    </div>
  );
};

const SectionHeader: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="text-[15px] text-foreground mb-4 pt-5 mt-4 border-t border-border/50 first:mt-0" style={{ fontFamily: "'Source Serif 4', serif" }}>
    {children}
  </div>
);

const FieldRow: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div className="flex gap-[18px] py-[5px] text-[14px] pl-2 items-center">
    <span className="text-muted-foreground/70 shrink-0 w-[90px] text-right">{label}</span>
    <div className="flex-1 min-w-0">{children}</div>
  </div>
);

/* ------------------------------------------------------------------ */
/*  Modal                                                             */
/* ------------------------------------------------------------------ */

export const ExportMetadataModal: React.FC<Props> = ({ open, onOpenChange }) => {
  const {
    latinFont,
    baseFont,
    outputFamilyName,
    outputWeight,
    outputItalic,
    outputWidth,
    outputDesigner,
    outputCopyright,
    outputUpm,
    isMerging,
    setOutputFamilyName,
    setOutputWeight,
    setOutputItalic,
    setOutputWidth,
    setOutputDesigner,
    setOutputCopyright,
    setOutputUpm,
  } = useMergeStore();

  // Use cached metadata from FontSource (no re-parsing needed)
  const jpMeta: SourceMeta | null = baseFont
    ? { copyright: baseFont.copyright || '', designer: baseFont.designer || '', familyName: baseFont.familyName }
    : null;
  const latMeta: SourceMeta | null = latinFont
    ? { copyright: latinFont.copyright || '', designer: latinFont.designer || '', familyName: latinFont.familyName }
    : null;
  const loading = false;

  // Title uses current family name
  const familyTitle = outputFamilyName || 'Export Metadata';
  const styleName = computeStyleName(outputWeight, outputItalic, outputWidth);

  // Source copyrights (read-only)
  const sourceCopyrights: string[] = [];
  if (jpMeta?.copyright) sourceCopyrights.push(jpMeta.copyright);
  if (latMeta?.copyright && latMeta.copyright !== jpMeta?.copyright)
    sourceCopyrights.push(latMeta.copyright);

  // Description with designer credit
  const descParts: string[] = [];
  for (const meta of [jpMeta, latMeta]) {
    if (!meta) continue;
    let part = meta.familyName;
    if (meta.designer) part += ` by ${meta.designer}`;
    descParts.push(part);
  }
  const description =
    descParts.length > 0
      ? `Based on ${descParts.join(' and ')}${latinFont ? '. Merged with OFL Font Baker.' : '. Baked with OFL Font Baker.'}`
      : '';

  const ready = !loading && (jpMeta || latMeta);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto min-h-[120px]">
        <DialogHeader>
          <DialogTitle>
            {familyTitle}
            <span className="text-muted-foreground font-normal ml-2">{styleName}</span>
          </DialogTitle>
        </DialogHeader>

        {loading && <div className="text-sm text-muted-foreground py-4">Loading...</div>}

        {ready && (
          <div>
            {/* ===== General ===== */}
            <SectionHeader>General</SectionHeader>

            <FieldRow label="Family">
              <input
                type="text"
                defaultValue={outputFamilyName}
                onBlur={(e) => {
                  setOutputFamilyName(e.target.value);
                  useMergeStore.getState().pushHistory();
                }}
                disabled={isMerging}
                className={cn(inputClass, isMerging && 'opacity-50 cursor-not-allowed')}
              />
            </FieldRow>

            <FieldRow label="Weight">
              <select
                value={outputWeight}
                onChange={(e) => setOutputWeight(Number(e.target.value))}
                disabled={isMerging}
                className={cn(selectClassName, isMerging && 'opacity-50 cursor-not-allowed')}
                style={selectArrowStyle}
              >
                {WEIGHT_MAP.map((w) => (
                  <option key={w.value} value={w.value}>
                    {w.label}
                  </option>
                ))}
              </select>
            </FieldRow>

            <FieldRow label="Width">
              <select
                value={outputWidth}
                onChange={(e) => setOutputWidth(Number(e.target.value))}
                disabled={isMerging}
                className={cn(selectClassName, isMerging && 'opacity-50 cursor-not-allowed')}
                style={selectArrowStyle}
              >
                {WIDTH_MAP.map((w) => (
                  <option key={w.value} value={w.value}>
                    {w.label}
                  </option>
                ))}
              </select>
            </FieldRow>

            <FieldRow label="UPM">
              <input
                type="number"
                min={16}
                max={16384}
                step={1}
                value={outputUpm}
                onChange={(e) => {
                  const n = Number(e.target.value);
                  if (Number.isFinite(n) && n > 0) setOutputUpm(Math.round(n));
                }}
                onBlur={() => useMergeStore.getState().pushHistory()}
                disabled={isMerging}
                className={cn(inputClass, isMerging && 'opacity-50 cursor-not-allowed')}
              />
            </FieldRow>

            <div className="flex gap-[18px] py-[5px] text-[14px] pl-2 items-center">
              <span className="text-muted-foreground/70 shrink-0 w-[90px] text-right leading-5">Italic</span>
              <button
                onClick={() => !isMerging && setOutputItalic(!outputItalic)}
                disabled={isMerging}
                className={cn(
                  'relative w-9 h-5 rounded-full transition-colors',
                  outputItalic ? 'bg-foreground' : 'bg-secondary',
                  isMerging && 'opacity-50 cursor-not-allowed',
                )}
              >
                <span
                  className={cn(
                    'absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-background transition-transform',
                    outputItalic && 'translate-x-4',
                  )}
                />
              </button>
            </div>

            {/* ===== Author ===== */}
            <SectionHeader>Author</SectionHeader>

            <FieldRow label="Designer">
              <input
                type="text"
                value={outputDesigner}
                onChange={(e) => setOutputDesigner(e.target.value)}
                onBlur={() => useMergeStore.getState().pushHistory()}
                disabled={isMerging}
                placeholder="Your name (optional)"
                className={cn(
                  inputClass,
                  'placeholder:text-foreground/30',
                  isMerging && 'opacity-50 cursor-not-allowed',
                )}
              />
            </FieldRow>
            <div className="pb-2" />

            {/* ===== Info ===== */}
            {description && (
              <>
                <SectionHeader>Info</SectionHeader>
                <InfoRow label="Description" value={description} />
              </>
            )}

            {/* ===== Legal ===== */}
            <SectionHeader>Legal</SectionHeader>

            <InfoRow label="Copyright" value={
              <div className="whitespace-pre-line">{sourceCopyrights.join('\n')}</div>
            } />

            <FieldRow label="">
              <input
                type="text"
                value={outputCopyright}
                onChange={(e) => setOutputCopyright(e.target.value)}
                onBlur={() => useMergeStore.getState().pushHistory()}
                disabled={isMerging}
                placeholder="Additional copyright (optional)"
                className={cn(inputClass, 'placeholder:text-foreground/30', isMerging && 'opacity-50 cursor-not-allowed')}
              />
            </FieldRow>
            <div className="h-[10px]" />

            <InfoRow
              label="License"
              value={<span className="text-[13px] leading-relaxed">{OFL_LICENSE_TEXT}</span>}
            />
            <InfoRow
              label="License URL"
              value={
                <a
                  href={OFL_LICENSE_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-500 hover:underline text-[14px]"
                >
                  {OFL_LICENSE_URL}
                </a>
              }
            />

            <div className="mt-4 p-3 rounded-md bg-secondary/50 text-xs text-muted-foreground leading-relaxed">
              OFL 1.1 requires derivative works to preserve all original copyright notices and
              distribute under the same license. Reserved Font Names from either source font must
              not appear in the output font name.
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
};
