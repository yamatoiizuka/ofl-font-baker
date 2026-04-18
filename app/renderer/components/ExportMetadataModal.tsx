import React from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/renderer/components/ui/dialog';
import { WEIGHT_MAP, WIDTH_MAP, computeStyleName } from '@/shared/constants';
import { useMergeStore } from '@/renderer/stores/mergeStore';
import { needsManualPostScriptName, sanitizePostScriptName } from '@/shared/postscript-name';
import { cn } from '@/renderer/lib/utils';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface SourceMeta {
  copyright: string;
  trademark: string;
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
  backgroundImage:
    "url(\"data:image/svg+xml,%3Csvg width='10' height='6' viewBox='0 0 10 6' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M1 1L5 5L9 1' stroke='%23999' stroke-width='1.2' stroke-linecap='round'/%3E%3C/svg%3E\")",
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
  <div
    className="text-[15px] text-foreground mb-4 pt-5 mt-4 border-t border-border/50 first:mt-0"
    style={{ fontFamily: "'Source Serif 4', serif" }}
  >
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
    familyName,
    postScriptName,
    postScriptNameDirty,
    version,
    fontWeight,
    fontItalic,
    fontWidth,
    designer,
    designerURL,
    manufacturer,
    manufacturerURL,
    copyright,
    upm,
    isMerging,
    setFamilyName,
    setPostScriptName,
    setVersion,
    setFontWeight,
    setFontItalic,
    setFontWidth,
    setDesigner,
    setDesignerURL,
    setManufacturer,
    setManufacturerURL,
    setCopyright,
    setUpm,
  } = useMergeStore();

  // PostScript name is auto-synced from family while it can be sanitized
  // without losing information. If the family contains non-ASCII or
  // disallowed characters, the input unlocks so the user can supply a
  // valid name manually. The inline "English only" hint is suppressed
  // once the user has committed their own value — at that point the
  // constraint has clearly been understood.
  const psNameNeedsManual = needsManualPostScriptName(familyName);
  const showPsNameHint = psNameNeedsManual && !postScriptNameDirty;
  // Flag when sanitization wipes the user's input to empty — nameID 6
  // cannot be empty, so Export is blocked until they supply something.
  const showPsNameError =
    psNameNeedsManual && postScriptNameDirty && postScriptName.trim().length === 0;

  // Use cached metadata from FontSource (no re-parsing needed)
  const jpMeta: SourceMeta | null = baseFont
    ? {
        copyright: baseFont.copyright || '',
        trademark: baseFont.trademark || '',
        designer: baseFont.designer || '',
        familyName: baseFont.familyName,
      }
    : null;
  const latMeta: SourceMeta | null = latinFont
    ? {
        copyright: latinFont.copyright || '',
        trademark: latinFont.trademark || '',
        designer: latinFont.designer || '',
        familyName: latinFont.familyName,
      }
    : null;
  const loading = false;

  // Title uses current family name
  const familyTitle = familyName || 'Export Metadata';
  const styleName = computeStyleName(fontWeight, fontItalic, fontWidth);

  // Source copyrights (read-only)
  const sourceCopyrights: string[] = [];
  if (jpMeta?.copyright) sourceCopyrights.push(jpMeta.copyright);
  if (latMeta?.copyright && latMeta.copyright !== jpMeta?.copyright)
    sourceCopyrights.push(latMeta.copyright);

  // Source trademarks (read-only, preserved as acknowledgment per OFL 1.1 §4)
  const sourceTrademarks: string[] = [];
  if (jpMeta?.trademark) sourceTrademarks.push(jpMeta.trademark);
  if (latMeta?.trademark && latMeta.trademark !== jpMeta?.trademark)
    sourceTrademarks.push(latMeta.trademark);

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

            <FieldRow label="Font Family">
              <input
                type="text"
                defaultValue={familyName}
                onBlur={(e) => {
                  setFamilyName(e.target.value);
                  useMergeStore.getState().pushHistory();
                }}
                disabled={isMerging}
                className={cn(inputClass, isMerging && 'opacity-50 cursor-not-allowed')}
              />
            </FieldRow>

            <FieldRow label="PostScript Name">
              <div>
                {showPsNameHint && (
                  <div className="text-[12px] text-amber-500 mb-1.5 flex items-center gap-1">
                    <span>⚠</span>
                    <span>English characters only</span>
                  </div>
                )}
                {showPsNameError && (
                  <div className="text-[12px] text-red-400 mb-1.5 flex items-center gap-1">
                    <span>⚠</span>
                    <span>PostScript Name is Required</span>
                  </div>
                )}
                <input
                  type="text"
                  value={postScriptName}
                  onChange={(e) => setPostScriptName(e.target.value)}
                  onBlur={(e) => {
                    // Strip disallowed chars on commit so non-ASCII typed
                    // into the field cannot leak into nameID 6.
                    const sanitized = sanitizePostScriptName(e.target.value);
                    if (sanitized !== e.target.value) setPostScriptName(sanitized);
                    useMergeStore.getState().pushHistory();
                  }}
                  disabled={isMerging || !psNameNeedsManual}
                  className={cn(
                    inputClass,
                    (isMerging || !psNameNeedsManual) && 'opacity-50 cursor-not-allowed',
                  )}
                />
              </div>
            </FieldRow>

            <FieldRow label="Weight">
              <select
                value={fontWeight}
                onChange={(e) => setFontWeight(Number(e.target.value))}
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
                value={fontWidth}
                onChange={(e) => setFontWidth(Number(e.target.value))}
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
                value={upm}
                onChange={(e) => {
                  const n = Number(e.target.value);
                  if (Number.isFinite(n) && n > 0) setUpm(Math.round(n));
                }}
                onBlur={() => useMergeStore.getState().pushHistory()}
                disabled={isMerging}
                className={cn(inputClass, isMerging && 'opacity-50 cursor-not-allowed')}
              />
            </FieldRow>

            <div className="flex gap-[18px] py-[5px] text-[14px] pl-2 items-center">
              <span className="text-muted-foreground/70 shrink-0 w-[90px] text-right leading-5">
                Italic
              </span>
              <button
                onClick={() => !isMerging && setFontItalic(!fontItalic)}
                disabled={isMerging}
                className={cn(
                  'relative w-9 h-5 rounded-full transition-colors',
                  fontItalic ? 'bg-foreground' : 'bg-secondary',
                  isMerging && 'opacity-50 cursor-not-allowed',
                )}
              >
                <span
                  className={cn(
                    'absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-background transition-transform',
                    fontItalic && 'translate-x-4',
                  )}
                />
              </button>
            </div>

            {/* ===== Author ===== */}
            <SectionHeader>Author</SectionHeader>

            <FieldRow label="Designer">
              <input
                type="text"
                value={designer}
                onChange={(e) => setDesigner(e.target.value)}
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

            <FieldRow label="Designer URL">
              <input
                type="text"
                value={designerURL}
                onChange={(e) => setDesignerURL(e.target.value)}
                onBlur={() => useMergeStore.getState().pushHistory()}
                disabled={isMerging}
                placeholder="https://example.com (optional)"
                className={cn(
                  inputClass,
                  'placeholder:text-foreground/30',
                  isMerging && 'opacity-50 cursor-not-allowed',
                )}
              />
            </FieldRow>

            <FieldRow label="Manufacturer">
              <input
                type="text"
                value={manufacturer}
                onChange={(e) => setManufacturer(e.target.value)}
                onBlur={() => useMergeStore.getState().pushHistory()}
                disabled={isMerging}
                placeholder="Organization (optional)"
                className={cn(
                  inputClass,
                  'placeholder:text-foreground/30',
                  isMerging && 'opacity-50 cursor-not-allowed',
                )}
              />
            </FieldRow>

            <FieldRow label="Manufacturer URL">
              <input
                type="text"
                value={manufacturerURL}
                onChange={(e) => setManufacturerURL(e.target.value)}
                onBlur={() => useMergeStore.getState().pushHistory()}
                disabled={isMerging}
                placeholder="https://example.com (optional)"
                className={cn(
                  inputClass,
                  'placeholder:text-foreground/30',
                  isMerging && 'opacity-50 cursor-not-allowed',
                )}
              />
            </FieldRow>

            <div className="pb-2" />

            {/* ===== Info ===== */}
            <SectionHeader>Info</SectionHeader>

            <FieldRow label="Version">
              <input
                type="text"
                value={version}
                onChange={(e) => setVersion(e.target.value)}
                onBlur={() => useMergeStore.getState().pushHistory()}
                disabled={isMerging}
                placeholder="1.000"
                className={cn(
                  inputClass,
                  'placeholder:text-foreground/30',
                  isMerging && 'opacity-50 cursor-not-allowed',
                )}
              />
            </FieldRow>

            {description && <InfoRow label="Description" value={description} />}

            {/* ===== Legal ===== */}
            <SectionHeader>Legal</SectionHeader>

            <InfoRow
              label="Copyright"
              value={<div className="whitespace-pre-line">{sourceCopyrights.join('\n')}</div>}
            />

            <FieldRow label="">
              <input
                type="text"
                value={copyright}
                onChange={(e) => setCopyright(e.target.value)}
                onBlur={() => useMergeStore.getState().pushHistory()}
                disabled={isMerging}
                placeholder="Additional copyright (optional)"
                className={cn(
                  inputClass,
                  'placeholder:text-foreground/30',
                  isMerging && 'opacity-50 cursor-not-allowed',
                )}
              />
            </FieldRow>
            <div className="h-[10px]" />

            {sourceTrademarks.length > 0 && (
              <InfoRow
                label="Trademark"
                value={
                  <div className="whitespace-pre-line">{sourceTrademarks.join('\n')}</div>
                }
              />
            )}

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
