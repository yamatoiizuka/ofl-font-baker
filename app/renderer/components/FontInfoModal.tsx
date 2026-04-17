/**
 * @fileoverview Modal dialog that displays detailed font metadata and a glyph map preview rendered with opentype.js.
 */

import React from 'react';
import { FontSource } from '@/shared/types';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/renderer/components/ui/dialog';

interface Props {
  font: FontSource;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** All name table fields we want to display. */
interface FontMeta {
  familyName: string;
  styleName: string;
  version: string;
  copyright: string;
  trademark: string;
  designer: string;
  designerURL: string;
  manufacturer: string;
  manufacturerURL: string;
  license: string;
  licenseURL: string;
  description: string;
  // OS/2
  fsType: number;
  vendorID: string;
  // Metrics
  unitsPerEm: number;
  glyphCount: number;
  ascender: number;
  descender: number;
  lineGap: number;
}

/**
 * Extracts a string value from an opentype.js name table field.
 * @param nameField - The name field value (string or locale object).
 * @returns The extracted string, preferring English then Japanese.
 */
function getStr(nameField: any): string {
  if (!nameField) return '';
  if (typeof nameField === 'string') return nameField;
  // opentype.js returns { en: "...", ja: "...", ... }
  return nameField.en || nameField.ja || Object.values(nameField)[0] || '';
}

/**
 * Converts an OS/2 fsType bitmask into a human-readable embedding description.
 * @param fsType - The fsType bitmask value from the OS/2 table.
 * @returns A comma-separated string of embedding permission flags.
 */
function describeFsType(fsType: number): string {
  if (fsType === 0) return 'Installable';
  const parts: string[] = [];
  if (fsType & 0x0002) parts.push('Restricted');
  if (fsType & 0x0004) parts.push('Preview & Print');
  if (fsType & 0x0008) parts.push('Editable');
  if (fsType & 0x0100) parts.push('No subsetting');
  if (fsType & 0x0200) parts.push('Bitmap only');
  return parts.join(', ') || `Unknown (0x${fsType.toString(16)})`;
}

/**
 * Extracts comprehensive font metadata from a parsed opentype.js font object.
 * @param font - The parsed opentype.js font object.
 * @param source - The FontSource for fallback values.
 * @returns A FontMeta object containing names, metrics, and technical details.
 */
function extractMeta(font: any, source: FontSource): FontMeta {
  const names = font.names || {};
  const os2 = (font as any).tables?.os2;
  const hhea = (font as any).tables?.hhea;

  return {
    familyName: getStr(names.fontFamily) || source.familyName,
    styleName: source.isVariable ? 'Variable' : (getStr(names.fontSubfamily) || source.styleName),
    version: getStr(names.version),
    copyright: getStr(names.copyright),
    trademark: getStr(names.trademark),
    designer: getStr(names.designer),
    designerURL: getStr(names.designerURL),
    manufacturer: getStr(names.manufacturer),
    manufacturerURL: getStr(names.manufacturerURL),
    license: getStr(names.license),
    licenseURL: getStr(names.licenseURL),
    description: getStr(names.description),
    fsType: os2?.fsType ?? 0,
    vendorID: os2?.achVendID ?? '',
    unitsPerEm: font.unitsPerEm ?? source.unitsPerEm,
    glyphCount: font.numGlyphs ?? source.glyphCount,
    ascender: os2?.sTypoAscender ?? hhea?.ascender ?? source.ascender,
    descender: os2?.sTypoDescender ?? hhea?.descender ?? 0,
    lineGap: os2?.sTypoLineGap ?? hhea?.lineGap ?? 0,
  };
}

/* ------------------------------------------------------------------ */
/*  Info row                                                          */
/* ------------------------------------------------------------------ */

/**
 * Renders a label-value row for displaying font metadata in the info modal.
 */
const InfoRow: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => {
  if (value === '' || value === null || value === undefined || value === 0) return null;
  return (
    <div className="flex gap-[18px] py-[4px] text-[14px] pl-2">
      <span className="text-muted-foreground/70 shrink-0 w-[90px] text-right">{label}</span>
      <span className="text-foreground min-w-0 break-words">{value}</span>
    </div>
  );
};

/**
 * Wraps a URL string in an anchor element for display, or returns null if empty.
 * @param url - The URL to render as a link.
 * @returns A React anchor element or null.
 */
function urlValue(url: string): React.ReactNode {
  if (!url) return null;
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-500 hover:underline break-all"
    >
      {url}
    </a>
  );
}

/**
 * Renders a styled uppercase section header divider for the font info modal.
 */
const Section: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <div className="py-5 border-t border-border/50">
    <div
      className="text-[15px] text-foreground mb-4"
      style={{ fontFamily: "'Source Serif 4', serif" }}
    >
      {title}
    </div>
    {children}
  </div>
);

/* ------------------------------------------------------------------ */
/*  Modal                                                             */
/* ------------------------------------------------------------------ */

/**
 * Modal dialog displaying detailed font metadata including names, metrics, licensing, and technical info.
 * Parses the font file on open to extract metadata from the name, OS/2, and hhea tables.
 */
export const FontInfoModal: React.FC<Props> = ({ font, open, onOpenChange }) => {
  // Always build meta from cached FontSource (stays during close animation)
  const meta: FontMeta = {
    familyName: font.familyName,
    styleName: font.styleName,
    version: font.version || '',
    copyright: font.copyright || '',
    trademark: '',
    designer: font.designer || '',
    designerURL: '',
    manufacturer: '',
    manufacturerURL: '',
    license: font.license || '',
    licenseURL: font.licenseURL || '',
    description: font.description || '',
    fsType: 0,
    vendorID: '',
    unitsPerEm: font.unitsPerEm,
    glyphCount: font.glyphCount,
    ascender: font.ascender,
    descender: 0,
    lineGap: 0,
  };
  const loading = false;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto min-h-[120px]">
        <DialogHeader>
          <DialogTitle>
            {font.familyName}
            <span className="text-muted-foreground font-normal ml-2">{font.styleName}</span>
          </DialogTitle>
        </DialogHeader>

        {loading && <div className="text-sm text-muted-foreground py-4">Loading...</div>}

        {meta && (
          <div>
            <Section title="General">
              <InfoRow label="Family" value={meta.familyName} />
              <InfoRow label="Style" value={meta.styleName} />
              <InfoRow label="Glyphs" value={meta.glyphCount.toLocaleString()} />
              <InfoRow label="UPM" value={String(meta.unitsPerEm)} />
            </Section>

            <Section title="Metrics">
              <InfoRow label="Ascender" value={String(meta.ascender)} />
              <InfoRow label="Descender" value={String(meta.descender)} />
              <InfoRow label="Line Gap" value={meta.lineGap !== 0 ? String(meta.lineGap) : null} />
            </Section>

            {(meta.designer || meta.designerURL || meta.manufacturer || meta.manufacturerURL) && (
              <Section title="Author">
                <InfoRow label="Designer" value={meta.designer} />
                <InfoRow label="Designer URL" value={urlValue(meta.designerURL)} />
                <InfoRow label="Manufacturer" value={meta.manufacturer} />
                <InfoRow label="Mfr. URL" value={urlValue(meta.manufacturerURL)} />
              </Section>
            )}

            {(meta.version || meta.description) && (
              <Section title="Info">
                <InfoRow label="Version" value={meta.version} />
                <InfoRow label="Description" value={meta.description} />
              </Section>
            )}

            {(meta.copyright || meta.trademark || meta.license || meta.licenseURL) && (
              <Section title="Legal">
                <InfoRow label="Copyright" value={meta.copyright} />
                <InfoRow label="Trademark" value={meta.trademark} />
                <InfoRow label="License" value={meta.license} />
                <InfoRow label="License URL" value={urlValue(meta.licenseURL)} />
              </Section>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
};
