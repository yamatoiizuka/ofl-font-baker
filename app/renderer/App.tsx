/**
 * @fileoverview Root React component that renders the main application layout with font cards, settings, preview, and export panels.
 */

import React, { useEffect, useState } from 'react';
import { FontCard } from '@/renderer/components/FontCard';
import { SettingsPanel } from '@/renderer/components/SettingsPanel';
import { GlyphPreview } from '@/renderer/components/GlyphPreview';
import { ExportPanel } from '@/renderer/components/ExportPanel';
import { AboutModal } from '@/renderer/components/AboutModal';
import { FontInfoModal } from '@/renderer/components/FontInfoModal';
import { ShortcutsModal } from '@/renderer/components/ShortcutsModal';
import { matchShortcut } from '@/shared/shortcuts';
import { useMergeStore } from '@/renderer/stores/mergeStore';
import { useFontLoader } from '@/renderer/hooks/useFontLoader';
import { useMerge } from '@/renderer/hooks/useMerge';
import mergeAllSvg from '@/renderer/assets/icons/merge-all.svg';
import mergeAllInactiveSvg from '@/renderer/assets/icons/merge-all-inactive.svg';

/**
 * Root application component providing a two-column layout with font input/settings
 * on the left and glyph preview with export controls on the right.
 */
const App: React.FC = () => {
  const {
    latinFont,
    baseFont,
    selectedRole,
    setSelectedRole,
    setLatinFont,
    setBaseFont,
    updateFontAdjustment,
    updateFontAxis,
  } = useMergeStore();
  const { pickAndLoadFont } = useFontLoader();
  const undo = useMergeStore((s) => s.undo);
  const redo = useMergeStore((s) => s.redo);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [settingsHovered, setSettingsHovered] = useState(false);
  const { startMerge } = useMerge();

  useEffect(() => {
    const unsubAbout = window.electronAPI?.onMenuAbout?.(() => setAboutOpen(true));
    const unsubShortcuts = window.electronAPI?.onMenuShortcuts?.(() => setShortcutsOpen(true));
    return () => {
      unsubAbout?.();
      unsubShortcuts?.();
    };
  }, []);

  // ⌘Z / ⌘⇧Z undo/redo (keyboard + menu)
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      const id = matchShortcut(e);
      if (!id) return;
      if (id === 'undo') {
        e.preventDefault();
        undo();
      } else if (id === 'redo') {
        e.preventDefault();
        redo();
      } else if (id === 'fontInfo') {
        const { selectedRole, latinFont, baseFont } = useMergeStore.getState();
        const f =
          selectedRole === 'latin' ? latinFont : selectedRole === 'base' ? baseFont : null;
        if (f) {
          e.preventDefault();
          setInfoOpen(true);
        }
      } else if (id === 'revealFont') {
        const { selectedRole, latinFont, baseFont } = useMergeStore.getState();
        const f =
          selectedRole === 'latin' ? latinFont : selectedRole === 'base' ? baseFont : null;
        if (f) {
          e.preventDefault();
          window.electronAPI.revealInFinder(f.path);
        }
      } else if (id === 'clearFont') {
        const { selectedRole, latinFont, baseFont } = useMergeStore.getState();
        const f =
          selectedRole === 'latin' ? latinFont : selectedRole === 'base' ? baseFont : null;
        if (f) {
          e.preventDefault();
          if (selectedRole === 'latin') setLatinFont(null);
          else if (selectedRole === 'base') setBaseFont(null);
        }
      } else if (id === 'export') {
        e.preventDefault();
        startMerge();
      } else if (id === 'shortcutsHelp') {
        e.preventDefault();
        setShortcutsOpen(true);
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    const unsubUndo = window.electronAPI?.onMenuUndo?.(() => undo());
    const unsubRedo = window.electronAPI?.onMenuRedo?.(() => redo());
    const unsubExport = window.electronAPI?.onMenuExport?.(() => startMerge());
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      unsubUndo?.();
      unsubRedo?.();
      unsubExport?.();
    };
  }, [undo, redo, startMerge, setLatinFont, setBaseFont]);

  const selectedFont =
    selectedRole === 'latin' ? latinFont : selectedRole === 'base' ? baseFont : null;
  const hoveredRole = useMergeStore((s) => s.hoveredRole);
  const screenshotMode = window.electronAPI?.isScreenshotMode;
  // In screenshot mode the Input column is narrowed so sliders crop out of frame;
  // hovering the active card expands it back to reveal the full panel.
  const inputColumnExpanded =
    !screenshotMode || hoveredRole === selectedRole || settingsHovered;

  // Validate persisted font paths on startup
  useEffect(() => {
    async function validateFonts() {
      for (const [font, role, setFont] of [
        [baseFont, 'base', setBaseFont],
        [latinFont, 'latin', setLatinFont],
      ] as const) {
        if (!font) continue;
        const exists = await window.electronAPI.checkFileExists(font.path);
        if (exists) continue;

        const label = role === 'base' ? 'Base font' : 'Latin font';
        const fileName = font.path.split('/').pop() || font.familyName || 'Unknown';
        const choice = await window.electronAPI.showMissingFontDialog(label, fileName);
        if (choice === 'select') {
          await pickAndLoadFont(role);
        } else {
          setFont(null);
        }
      }
    }
    validateFonts();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="h-screen flex bg-background text-foreground font-sans">
      {/* ===== Drag region: top 50px across full width ===== */}
      <div
        className="fixed top-0 left-0 right-0 h-[40px] z-50"
        style={{ WebkitAppRegion: 'drag' } as React.CSSProperties}
      />

      {/* ===== INPUT column ===== */}
      <div
        className="shrink-0 border-r border-border flex flex-col bg-card transition-[width] duration-300 ease-out"
        style={{ width: inputColumnExpanded ? 540 : 248 }}
      >
        <div
          className="shrink-0 px-8 pt-[54px] pb-8"
          style={{ WebkitAppRegion: 'drag' } as React.CSSProperties}
        >
          <h1
            className="text-[21px] tracking-[0.01em]"
            style={{ fontFamily: "'Source Serif 4', serif" }}
          >
            Input
          </h1>
        </div>

        <div className="flex-1 flex gap-[27px] px-8 min-h-0 overflow-y-auto overflow-x-hidden">
          <div className="w-[180px] shrink-0 space-y-3 pb-8">
            <FontCard
              role="base"
              font={baseFont}
              isSelected={selectedRole === 'base'}
              onSelect={() => baseFont && setSelectedRole('base')}
            />

            <div className="flex flex-col items-center -mb-[.36rem] relative z-10">
              <img
                src={latinFont ? mergeAllSvg : mergeAllInactiveSvg}
                alt="Merge All"
                className="w-[62px]"
                draggable={false}
              />
            </div>

            <FontCard
              role="latin"
              font={latinFont}
              isSelected={selectedRole === 'latin'}
              onSelect={() => latinFont && setSelectedRole('latin')}
            />
          </div>

          <div
            className="flex-1 flex flex-col min-h-0 overflow-y-auto"
            onMouseEnter={() => setSettingsHovered(true)}
            onMouseLeave={() => setSettingsHovered(false)}
          >
            {selectedFont && selectedRole ? (
              <SettingsPanel
                font={selectedFont}
                role={selectedRole}
                onUpdateBaseline={(v) => updateFontAdjustment(selectedRole, { baselineOffset: v })}
                onUpdateScale={(v) => updateFontAdjustment(selectedRole, { scale: v })}
                onUpdateAxis={(tag, value) => updateFontAxis(selectedRole, tag, value)}
              />
            ) : (
              <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground/40">
                Select a font
              </div>
            )}
          </div>
        </div>
        {/* Spacer matching ExportPanel height so "Select a font" aligns with "Load fonts..." */}
        {!(selectedFont && selectedRole) && <div className="shrink-0 h-[115.5px]" aria-hidden />}
      </div>

      {/* ===== OUTPUT column ===== */}
      <div className="flex-1 flex flex-col min-w-0">
        <GlyphPreview />
        <ExportPanel />
      </div>

      <AboutModal open={aboutOpen} onOpenChange={setAboutOpen} />
      <ShortcutsModal open={shortcutsOpen} onOpenChange={setShortcutsOpen} />
      {selectedFont && (
        <FontInfoModal font={selectedFont} open={infoOpen} onOpenChange={setInfoOpen} />
      )}
    </div>
  );
};

export default App;
