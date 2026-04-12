/**
 * @fileoverview Keyboard shortcuts reference modal, generated from the
 * central SHORTCUTS registry and grouped by section.
 */

import React from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/renderer/components/ui/dialog';
import {
  SHORTCUT_HELP,
  parseAccelerator,
  type ShortcutDef,
  type ShortcutSection,
} from '@/shared/shortcuts';

const capCls =
  'inline-flex items-center justify-center min-w-[20px] h-[20px] px-1 rounded-[4px] bg-secondary/60 font-sans text-[13px] leading-none text-muted-foreground';
const spacerCls = 'inline-block min-w-[20px] h-[20px]';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const SECTION_ORDER: ShortcutSection[] = ['General', 'Input', 'Export'];

/**
 * Groups deduped help entries by section. Aliases (same id) are collapsed
 * to the primary entry — only its accelerator is shown in the modal.
 */
function groupBySection(): Record<ShortcutSection, ShortcutDef[]> {
  const out: Record<string, ShortcutDef[]> = {};
  for (const s of SHORTCUT_HELP) {
    (out[s.section] ||= []).push(s);
  }
  return out as Record<ShortcutSection, ShortcutDef[]>;
}

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

/**
 * Lists every registered keyboard shortcut, grouped by section.
 */
export const ShortcutsModal: React.FC<Props> = ({ open, onOpenChange }) => {
  const isMac = navigator.platform.toLowerCase().includes('mac');
  const grouped = groupBySection();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto min-h-[120px]">
        <DialogHeader>
          <DialogTitle>Keyboard Shortcuts</DialogTitle>
        </DialogHeader>

        <div>
          {SECTION_ORDER.map((sec) => {
            const items = grouped[sec];
            if (!items || items.length === 0) return null;
            return (
              <Section key={sec} title={sec}>
                <ul className="space-y-2">
                  {items.map((s) => (
                    <li key={s.id} className="flex items-center gap-6 text-sm">
                      <span className="shrink-0 flex gap-1">
                        {(() => {
                          const p = parseAccelerator(s.accelerator, isMac);
                          return (
                            <>
                              {p.shift || p.alt ? (
                                <kbd className={capCls}>{p.shift || p.alt}</kbd>
                              ) : (
                                <span className={spacerCls} aria-hidden />
                              )}
                              {p.cmd && <kbd className={capCls}>{p.cmd}</kbd>}
                              {p.key && <kbd className={capCls}>{p.key}</kbd>}
                            </>
                          );
                        })()}
                      </span>
                      <span className="text-foreground">{s.label}</span>
                    </li>
                  ))}
                </ul>
              </Section>
            );
          })}
        </div>
      </DialogContent>
    </Dialog>
  );
};
