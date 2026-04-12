/**
 * @fileoverview Font card component for selecting and displaying a Latin or Japanese font source with drag-and-drop support.
 */

import React, { useState, useEffect, useRef } from 'react';
import { FontSource } from '@/shared/types';
import { useFontLoader } from '@/renderer/hooks/useFontLoader';
import { useMergeStore } from '@/renderer/stores/mergeStore';
import { FontInfoModal } from '@/renderer/components/FontInfoModal';
import clearSvg from '@/renderer/assets/icons/clear.svg';
import infoSvg from '@/renderer/assets/icons/info.svg';
import baseFontSvg from '@/renderer/assets/icons/base-font.svg';
import subFontSvg from '@/renderer/assets/icons/sub-font.svg';

interface Props {
  role: 'latin' | 'base';
  font: FontSource | null;
  isSelected: boolean;
  onSelect: () => void;
}

const DEFAULT_SAMPLE = { latin: 'Aa', base: 'あ永' };

/**
 * Displays a font card with sample text preview, drag-and-drop loading, and font info access.
 * Supports selection highlighting and inline font-face rendering.
 */
export const FontCard: React.FC<Props> = ({ role, font, isSelected, onSelect }) => {
  const { pickAndLoadFont, handleDrop } = useFontLoader();
  const store = useMergeStore();
  const [isDragOver, setIsDragOver] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false);
  const [hoverSuppressed, setHoverSuppressed] = useState(false);
  const [fontFamily, setFontFamily] = useState<string | null>(null);
  const cardRef = useRef<HTMLDivElement | null>(null);
  const urlRef = useRef<string | null>(null);

  const isBase = role === 'base';
  const label = isBase ? 'Base Font' : 'Latin, Kana';
  const screenshotMode = window.electronAPI?.isScreenshotMode;

  // Register @font-face for card preview
  useEffect(() => {
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
    if (!font) {
      setFontFamily(null);
      return;
    }

    const family = `__card_${role}__`;
    (async () => {
      try {
        const buffer = await window.electronAPI.readFontFile(font.path);
        const blob = new Blob([buffer], { type: 'font/ttf' });
        const url = URL.createObjectURL(blob);
        urlRef.current = url;
        const face = new FontFace(family, `url(${url})`);
        await face.load();
        document.fonts.forEach((f) => {
          if (f.family === family) document.fonts.delete(f);
        });
        document.fonts.add(face);
        setFontFamily(family);
      } catch {
        setFontFamily(null);
      }
    })();
  }, [font?.path, role]);

  const variationSettings =
    font?.isVariable && font.axes.length
      ? font.axes.map((a) => `"${a.tag}" ${a.currentValue}`).join(', ')
      : 'normal';

  useEffect(() => {
    if (!hoverSuppressed) return;

    const handlePointerMove = (e: PointerEvent) => {
      const card = cardRef.current;
      if (!card) {
        setHoverSuppressed(false);
        return;
      }

      const rect = card.getBoundingClientRect();
      const isInside =
        e.clientX >= rect.left &&
        e.clientX <= rect.right &&
        e.clientY >= rect.top &&
        e.clientY <= rect.bottom;

      if (!isInside) setHoverSuppressed(false);
    };

    window.addEventListener('pointermove', handlePointerMove);
    return () => window.removeEventListener('pointermove', handlePointerMove);
  }, [hoverSuppressed]);

  function openInfoModal() {
    store.setHoveredRole(null);
    setHoverSuppressed(true);
    setInfoOpen(true);
  }

  return (
    <div
      ref={cardRef}
      onClick={() => (font ? onSelect() : pickAndLoadFont(role))}
      onDoubleClick={() => pickAndLoadFont(role)}
      onContextMenu={async (e) => {
        e.preventDefault();
        if (!font) return;
        const action = await window.electronAPI.showCardContextMenu({
          hasFont: true,
          fontPath: font.path,
        });
        if (action === 'info') {
          openInfoModal();
        } else if (action === 'reveal') {
          window.electronAPI.revealInFinder(font.path);
        } else if (action === 'clear') {
          if (role === 'latin') store.setLatinFont(null);
          else store.setBaseFont(null);
        }
      }}
      onDragOver={(e) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragOver(true);
      }}
      onDragEnter={(e) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragOver(true);
      }}
      onDragLeave={(e) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragOver(false);
      }}
      onDrop={(e) => {
        setIsDragOver(false);
        handleDrop(role, e);
      }}
      className="aspect-square rounded-lg pt-3 px-4 pb-3 cursor-pointer transition-all select-none flex flex-col relative group"
      style={{
        boxShadow: isDragOver
          ? 'inset 0 0 0 2px color-mix(in oklch, var(--color-highlight), transparent 50%)'
          : isSelected
            ? 'inset 0 0 0 2px var(--color-highlight)'
            : font
              ? 'inset 0 0 0 1px var(--color-border)'
              : 'none',
        background: font ? 'var(--color-background)' : undefined,
      }}
      onMouseEnter={() => {
        if (font && !hoverSuppressed) store.setHoveredRole(role);
      }}
      onMouseLeave={() => {
        store.setHoveredRole(null);
        setHoverSuppressed(false);
      }}
    >
      {/* Dashed border overlay for empty card */}
      {!font && !isDragOver && (
        <svg className="absolute inset-0 w-full h-full pointer-events-none" overflow="visible">
          <rect
            x="0.5"
            y="0.5"
            width="calc(100% - 1px)"
            height="calc(100% - 1px)"
            rx="8"
            ry="8"
            fill="none"
            stroke="var(--color-border)"
            strokeWidth="1"
            strokeDasharray="6 4"
          />
        </svg>
      )}

      {/* Clear button (top-right, visible on hover) */}
      {font && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            if (role === 'latin') store.setLatinFont(null);
            else store.setBaseFont(null);
          }}
          className="absolute top-[14px] right-3 opacity-0 group-hover:opacity-100 transition-opacity"
        >
          <img src={clearSvg} alt="Clear" width={14} height={14} draggable={false} />
        </button>
      )}

      {font ? (
        <>
          {/* Label (top-center) */}
          <div className="text-[14px] text-center text-[#000]">{label}</div>

          {/* Sample text */}
          <div className="flex-1 flex items-center justify-center">
            {fontFamily && (
              <div
                className="leading-tight truncate"
                style={{
                  fontSize: role === 'latin' ? 32 : 40,
                  fontFamily: `"${fontFamily}", sans-serif`,
                  fontVariationSettings: variationSettings,
                }}
              >
                {font.sampleText || DEFAULT_SAMPLE[role]}
              </div>
            )}
          </div>

          {/* Font name (center, with margin for icons unless in screenshot mode) */}
          <div
            className={`text-[13px] text-[#000] truncate text-center ${screenshotMode ? 'mx-2' : 'mx-6'}`}
          >
            {font.familyName}
          </div>
          {/* Info icon (bottom-right, aligned with font name) — hidden in screenshot mode */}
          {!screenshotMode && (
            <button
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.stopPropagation();
                openInfoModal();
              }}
              className="absolute bottom-[14px] right-3 info-btn"
            >
              <img src={infoSvg} alt="Info" width={14} height={14} draggable={false} />
            </button>
          )}

          <FontInfoModal
            font={font}
            open={infoOpen}
            onOpenChange={(v) => {
              setInfoOpen(v);
              if (!v) {
                store.setHoveredRole(null);
                setHoverSuppressed(true);
              }
            }}
          />
        </>
      ) : (
        <>
          {/* Label (top-center, same position as loaded card) */}
          <div className="text-[14px] text-center text-muted-foreground">{label}</div>

          {/* Upload icon (center) */}
          <div className="flex-1 flex items-center justify-center">
            <img
              src={isBase ? baseFontSvg : subFontSvg}
              alt={label}
              style={{ height: 26, width: 'auto' }}
              draggable={false}
            />
          </div>

          {/* Extension hint (bottom, same position as font name) */}
          <div
            className="text-[13px] text-muted-foreground/50 truncate text-center mx-6"
            style={{ fontFamily: "'Source Serif 4', serif" }}
          >
            .otf&#8201;/&#8201;.ttf
          </div>
        </>
      )}
    </div>
  );
};
