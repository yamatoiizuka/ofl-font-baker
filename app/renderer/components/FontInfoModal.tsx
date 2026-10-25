/**
 * @fileoverview Modal dialog that displays the metadata cached on a FontSource.
 */

import React from 'react';
import { FontSource } from '@/shared/types';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/renderer/components/ui/dialog';

interface Props {
  font: FontSource;
  open: boolean;
  onOpenChange: (open: boolean) => void;
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
 */
export const FontInfoModal: React.FC<Props> = ({ font, open, onOpenChange }) => {
  // Read from the cached FontSource so content stays during the close animation
  const meta = {
    ...font,
    version: font.version || '',
    copyright: font.copyright || '',
    trademark: font.trademark || '',
    designer: font.designer || '',
    designerURL: font.designerURL || '',
    manufacturer: font.manufacturer || '',
    manufacturerURL: font.manufacturerURL || '',
    license: font.license || '',
    licenseURL: font.licenseURL || '',
    description: font.description || '',
    vendorID: font.vendorID || '',
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto min-h-[120px]">
        <DialogHeader>
          <DialogTitle>
            {font.familyName}
            <span className="text-muted-foreground font-normal ml-2">{font.styleName}</span>
          </DialogTitle>
        </DialogHeader>

        <div>
          <Section title="General">
            <InfoRow label="Family" value={meta.familyName} />
            <InfoRow label="Style" value={meta.styleName} />
            <InfoRow label="Glyphs" value={meta.glyphCount.toLocaleString()} />
            <InfoRow label="UPM" value={String(meta.unitsPerEm)} />
          </Section>

          <Section title="Metrics">
            <InfoRow label="Ascender" value={String(meta.ascender)} />
          </Section>

          {(meta.designer ||
            meta.designerURL ||
            meta.manufacturer ||
            meta.manufacturerURL ||
            meta.vendorID.trim()) && (
            <Section title="Author">
              <InfoRow label="Designer" value={meta.designer} />
              <InfoRow label="Designer URL" value={urlValue(meta.designerURL)} />
              <InfoRow label="Manufacturer" value={meta.manufacturer} />
              <InfoRow label="Manufacturer URL" value={urlValue(meta.manufacturerURL)} />
              <InfoRow label="Vendor ID" value={meta.vendorID.trim() || null} />
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
      </DialogContent>
    </Dialog>
  );
};
