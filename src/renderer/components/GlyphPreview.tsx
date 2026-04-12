/**
 * @fileoverview Canvas-based glyph preview component that renders shaped text using HarfBuzz with interactive selection.
 */

import React, { useEffect, useRef, useState } from 'react';
import { useMergeStore } from '@/renderer/stores/mergeStore';
import { FontSource } from '@/shared/types';
import { CURSOR_BLINK_INTERVAL_MS } from '@/shared/constants';
import {
  getHB,
  createFontHandle,
  destroyFontHandle,
  shapeText,
  drawCached,
  hitTestClick,
  navigateVertical,
  type FontHandle,
  type ShapeCache,
  type CharEdge,
} from '@/renderer/lib/hb-renderer';

import scaleSvg from '@/renderer/assets/icons/scale.svg';
import resetSvg from '@/renderer/assets/icons/reset.svg';
import { DEFAULT_TEXT } from '@/renderer/stores/mergeStore';

export const MIN_FONT_SIZE = 10;
export const MAX_FONT_SIZE = 80;
export const DEFAULT_FONT_SIZE = 27;
export const ZOOM_STEP = 4;

/**
 * Canvas-based font preview component with HarfBuzz text shaping, cursor editing,
 * selection support, and live variable axis updates.
 */
export const GlyphPreview: React.FC = () => {
  const latinFont = useMergeStore((s) => s.latinFont);
  const baseFont = useMergeStore((s) => s.baseFont);
  const selectedRole = useMergeStore((s) => s.selectedRole);
  const rawHoveredRole = useMergeStore((s) => s.hoveredRole);
  const hoveredRole = rawHoveredRole === selectedRole ? rawHoveredRole : null;
  const sampleText = useMergeStore((s) => s.sampleText);
  const setSampleText = useMergeStore((s) => s.setSampleText);
  const pushHistory = useMergeStore((s) => s.pushHistory);
  const showBaseline = useMergeStore((s) => s.showBaseline);
  const previewFontSize = useMergeStore((s) => s.previewFontSize);
  const setPreviewFontSize = useMergeStore((s) => s.setPreviewFontSize);
  const [resetHover, setResetHover] = useState(false);
  const [containerWidth, setContainerWidth] = useState(800);
  const [latHandle, setLatHandle] = useState<FontHandle | null>(null);
  const [jpHandle, setJpHandle] = useState<FontHandle | null>(null);
  const [cache, setCache] = useState<ShapeCache | null>(null);

  // Selection state in refs — we control redraw manually
  const selStartRef = useRef<number | null>(null); // anchor
  const selEndRef = useRef<number | null>(null); // active end
  const focusedRef = useRef(false);
  const blinkOn = useRef(true);
  const edgesRef = useRef<CharEdge[]>([]);
  const blinkTimer = useRef<ReturnType<typeof setInterval>>(undefined);
  const isDragging = useRef(false);
  const isContextMenu = useRef(false);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const hiddenRef = useRef<HTMLTextAreaElement>(null);
  const latHandleRef = useRef<FontHandle | null>(null);
  const jpHandleRef = useRef<FontHandle | null>(null);

  // We store the latest cache/font in refs so draw() always reads fresh values
  const cacheRef = useRef<ShapeCache | null>(null);
  cacheRef.current = cache;
  const latFontRef = useRef(latinFont);
  latFontRef.current = latinFont;
  const jpFontRef = useRef(baseFont);
  jpFontRef.current = baseFont;
  const hoveredRoleRef = useRef(hoveredRole);
  hoveredRoleRef.current = hoveredRole;
  const showBaselineRef = useRef(showBaseline);
  showBaselineRef.current = showBaseline;
  const fontSizeRef = useRef(previewFontSize);
  fontSizeRef.current = previewFontSize;
  // When true, the next draw() scrolls the cursor line into view. Set by
  // cursorMoved() so blink re-draws don't fight user scrolling.
  const needsScrollRef = useRef(false);

  /**
   * Builds a variation axis map from a font source for HarfBuzz configuration.
   * @param font - The font source to extract variation axes from, or null.
   * @returns A record mapping axis tags to their current values.
   */
  function buildVariations(font: FontSource | null): Record<string, number> {
    if (!font?.isVariable) return {};
    const vars: Record<string, number> = {};
    for (const axis of font.axes) vars[axis.tag] = axis.currentValue;
    return vars;
  }

  // Keys: path-only for font loading, axis-only for variation updates
  const latPathKey = latinFont?.path ?? '';
  const jpPathKey = baseFont?.path ?? '';
  const latAxisKey = latinFont?.axes.map((a) => `${a.tag}=${a.currentValue}`).join(',') ?? '';
  const jpAxisKey = baseFont?.axes.map((a) => `${a.tag}=${a.currentValue}`).join(',') ?? '';

  // --- Font loading (only on path change — expensive) ---
  useEffect(() => {
    let c = false;
    if (latHandleRef.current) {
      destroyFontHandle(latHandleRef.current);
      latHandleRef.current = null;
    }
    setLatHandle(null);
    if (!latinFont) return;
    (async () => {
      try {
        const hb = await getHB();
        const buf = await window.electronAPI.readFontFile(latinFont.path);
        const h = await createFontHandle(hb, buf, buildVariations(latinFont));
        if (!c) {
          latHandleRef.current = h;
          setLatHandle(h);
        }
      } catch (e) {
        console.error('HB EN:', e);
      }
    })();
    return () => {
      c = true;
    };
  }, [latPathKey]);

  useEffect(() => {
    let c = false;
    if (jpHandleRef.current) {
      destroyFontHandle(jpHandleRef.current);
      jpHandleRef.current = null;
    }
    setJpHandle(null);
    if (!baseFont) return;
    (async () => {
      try {
        const hb = await getHB();
        const buf = await window.electronAPI.readFontFile(baseFont.path);
        const h = await createFontHandle(hb, buf, buildVariations(baseFont));
        if (!c) {
          jpHandleRef.current = h;
          setJpHandle(h);
        }
      } catch (e) {
        console.error('HB JP:', e);
      }
    })();
    return () => {
      c = true;
    };
  }, [jpPathKey]);

  // --- Axis variation update (instant — no file reload) ---
  useEffect(() => {
    if (latHandle && latinFont?.isVariable) {
      latHandle.hbFont.setVariations(buildVariations(latinFont));
    }
  }, [latAxisKey, latHandle]);

  useEffect(() => {
    if (jpHandle && baseFont?.isVariable) {
      jpHandle.hbFont.setVariations(buildVariations(baseFont));
    }
  }, [jpAxisKey, jpHandle]);

  // --- Track container width for line wrapping ---
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) setContainerWidth(entry.contentRect.width);
    });
    ro.observe(el);
    setContainerWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  // --- Shaping (re-run on text, font, axis, or width change) ---
  useEffect(() => {
    if (!latHandle && !jpHandle) {
      setCache(null);
      return;
    }
    let c = false;
    shapeText(sampleText, latHandle, jpHandle).then((r) => {
      if (!c) setCache(r);
    });
    return () => {
      c = true;
    };
  }, [sampleText, latHandle, jpHandle, latAxisKey, jpAxisKey]);

  /**
   * Renders the shaped text cache onto the canvas, handling DPR scaling, line wrapping,
   * selection highlighting, cursor blinking, and baseline guides.
   */
  function draw() {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    const c = cacheRef.current;
    if (!canvas || !container || !c) return;

    const dpr = window.devicePixelRatio || 1;
    const w = container.clientWidth;

    // First pass: compute content height
    const fontSize = fontSizeRef.current;
    const lineHeightPx = c.lineHeight * (fontSize / c.baseUpem);
    const numVisualLines = c.lines.reduce((count, line) => {
      // Estimate wrapped lines per source line
      let x = 32; // paddingX
      let lines = 1;
      for (const g of line.glyphs) {
        const scale = g.isLatin
          ? (latFontRef.current?.scale ?? 1.0)
          : (jpFontRef.current?.scale ?? 1.0);
        const adv = g.advance * fontSize * scale;
        if (x + adv > w - 32 && x > 32) {
          lines++;
          x = 32;
        }
        x += adv;
      }
      return count + lines;
    }, 0);
    const contentH = Math.max(container.clientHeight, numVisualLines * lineHeightPx + 40);

    canvas.width = w * dpr;
    canvas.height = contentH * dpr;
    canvas.style.width = `${w}px`;
    canvas.style.height = `${contentH}px`;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, contentH);
    ctx.fillStyle =
      getComputedStyle(document.documentElement).getPropertyValue('--color-foreground').trim() ||
      '#000';

    const focused = focusedRef.current;
    const edges = drawCached(ctx, c, {
      fontSize: fontSizeRef.current,
      latScale: latFontRef.current?.scale ?? 1.0,
      latBaseline: latFontRef.current?.baselineOffset ?? 0,
      jpScale: jpFontRef.current?.scale ?? 1.0,
      jpBaseline: jpFontRef.current?.baselineOffset ?? 0,
      selStart: focused ? selStartRef.current : null,
      selEnd: focused ? selEndRef.current : null,
      showCursor: focused && blinkOn.current,
      paddingX: 32,
      paddingY: 4,
      canvasWidth: container.clientWidth,
      showBaseline: showBaselineRef.current,
      highlightRole: hoveredRoleRef.current,
    });
    edgesRef.current = edges;

    // Move hidden textarea to active cursor position for IME
    if (focused && selEndRef.current != null) {
      const edge = edges.find((e) => e.charIndex === selEndRef.current);
      if (edge && hiddenRef.current) {
        const rect = canvas.getBoundingClientRect();
        hiddenRef.current.style.left = `${rect.left + edge.x}px`;
        hiddenRef.current.style.top = `${rect.top + edge.y}px`;
      }
      // Scroll the cursor line into view if requested — only after explicit
      // cursor movement, not on every blink tick (would hijack user scroll).
      if (needsScrollRef.current && edge && container && cacheRef.current) {
        needsScrollRef.current = false;
        const pxPerBase = fontSizeRef.current / cacheRef.current.baseUpem;
        const lineTop = edge.y - cacheRef.current.ascender * pxPerBase;
        const lineHeightPx = cacheRef.current.lineHeight * pxPerBase;
        const lineBottom = lineTop + lineHeightPx;
        const viewTop = container.scrollTop;
        const viewBottom = viewTop + container.clientHeight;
        const margin = 8;
        if (lineTop < viewTop + margin) {
          container.scrollTop = Math.max(0, lineTop - margin);
        } else if (lineBottom > viewBottom - margin) {
          container.scrollTop = lineBottom - container.clientHeight + margin;
        }
      }
    }
  }

  // --- Redraw triggers ---
  // On cache or geometry change (React state driven)
  useEffect(() => {
    draw();
  }, [
    cache,
    showBaseline,
    previewFontSize,
    containerWidth,
    latinFont?.scale,
    latinFont?.baselineOffset,
    baseFont?.scale,
    baseFont?.baselineOffset,
    hoveredRole,
  ]);

  /**
   * Starts the cursor blink interval timer and immediately shows the cursor.
   */
  function startBlink() {
    clearInterval(blinkTimer.current);
    blinkOn.current = true;
    blinkTimer.current = setInterval(() => {
      blinkOn.current = !blinkOn.current;
      draw();
    }, CURSOR_BLINK_INTERVAL_MS);
  }
  /**
   * Stops the cursor blink interval timer and hides the cursor.
   */
  function stopBlink() {
    clearInterval(blinkTimer.current);
    blinkOn.current = false;
  }

  /**
   * Resets the blink timer and triggers a redraw after a cursor position change.
   */
  function cursorMoved() {
    needsScrollRef.current = true;
    startBlink();
    draw();
  }

  /**
   * Synchronizes the cursor/selection state from the hidden textarea to the canvas refs.
   */
  function syncCursor() {
    if (!hiddenRef.current) return;
    const s = hiddenRef.current.selectionStart;
    const e = hiddenRef.current.selectionEnd;
    if (s !== selStartRef.current || e !== selEndRef.current) {
      selStartRef.current = s;
      selEndRef.current = e;
      cursorMoved();
    }
  }

  /**
   * Handles mouse down events on the canvas for cursor placement and selection start.
   * @param e - The React mouse event.
   */
  function handleMouseDown(e: React.MouseEvent) {
    e.preventDefault(); // Prevent browser from stealing focus from hidden textarea
    // Right-click: just prevent default, don't change selection
    if (e.button !== 0) {
      isContextMenu.current = true;
      return;
    }
    // Record history on click (captures text edits since last snapshot)
    pushHistory();

    const canvas = canvasRef.current;
    if (!canvas || !cacheRef.current) return;

    hiddenRef.current?.focus();
    focusedRef.current = true;

    const rect = canvas.getBoundingClientRect();
    const pos = hitTestClick(edgesRef.current, e.clientX - rect.left, e.clientY - rect.top);

    if (e.shiftKey) {
      // Extend selection
      selEndRef.current = pos;
    } else {
      selStartRef.current = pos;
      selEndRef.current = pos;
    }

    if (hiddenRef.current) {
      hiddenRef.current.selectionStart = selStartRef.current ?? pos;
      hiddenRef.current.selectionEnd = pos;
    }
    isDragging.current = true;
    cursorMoved();
  }

  /**
   * Handles mouse move events for extending text selection during drag.
   * @param e - The React mouse event.
   */
  function handleMouseMove(e: React.MouseEvent) {
    if (!isDragging.current || !cacheRef.current) return;
    const canvas = canvasRef.current;
    if (!canvas) return;

    const rect = canvas.getBoundingClientRect();
    const pos = hitTestClick(edgesRef.current, e.clientX - rect.left, e.clientY - rect.top);

    selEndRef.current = pos;
    if (hiddenRef.current) {
      hiddenRef.current.selectionStart = Math.min(selStartRef.current ?? pos, pos);
      hiddenRef.current.selectionEnd = Math.max(selStartRef.current ?? pos, pos);
    }
    draw();
  }

  /**
   * Handles mouse up events to end drag selection.
   */
  function handleMouseUp() {
    isDragging.current = false;
  }

  /**
   * Handles focus events to activate cursor blinking and redraw.
   */
  function handleFocus() {
    focusedRef.current = true;
    startBlink();
    draw();
  }

  /**
   * Handles blur events to clear selection and stop cursor blinking.
   */
  function handleBlur() {
    if (isContextMenu.current) return; // Keep selection during context menu
    focusedRef.current = false;
    selStartRef.current = null;
    selEndRef.current = null;
    stopBlink();
    draw();
    pushHistory();
  }

  /**
   * Handles text input changes from the hidden textarea and syncs the cursor.
   * @param e - The React change event from the textarea.
   */
  const textHistoryTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  function handleChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setSampleText(e.target.value);
    setTimeout(syncCursor, 0);
    // Debounce: commit undo snapshot after 500ms of idle
    clearTimeout(textHistoryTimer.current);
    textHistoryTimer.current = setTimeout(() => pushHistory(), 500);
  }

  /**
   * Handles keyboard events for vertical cursor navigation and cursor sync.
   * @param e - The React keyboard event.
   */
  function handleKeyDown(e: React.KeyboardEvent) {
    if (
      (e.key === 'ArrowUp' || e.key === 'ArrowDown') &&
      cacheRef.current &&
      selEndRef.current != null
    ) {
      e.preventDefault();
      const newPos = navigateVertical(
        edgesRef.current,
        selEndRef.current,
        e.key === 'ArrowUp' ? 'up' : 'down',
      );
      if (e.shiftKey) {
        selEndRef.current = newPos;
      } else {
        selStartRef.current = newPos;
        selEndRef.current = newPos;
      }
      if (hiddenRef.current) {
        const lo = Math.min(selStartRef.current ?? newPos, newPos);
        const hi = Math.max(selStartRef.current ?? newPos, newPos);
        hiddenRef.current.selectionStart = lo;
        hiddenRef.current.selectionEnd = hi;
      }
      cursorMoved();
    } else {
      setTimeout(syncCursor, 0);
    }
  }

  // Global mouseup
  useEffect(() => {
    const up = () => {
      isDragging.current = false;
    };
    window.addEventListener('mouseup', up);
    return () => window.removeEventListener('mouseup', up);
  }, []);

  const hasAnyFont = latinFont || baseFont;

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Header — same structure as INPUT */}
      <div
        className="shrink-0 px-8 pt-[54px] pb-8"
        style={{ WebkitAppRegion: 'drag' } as React.CSSProperties}
      >
        <div className="flex items-center justify-between">
          <h1
            className="text-[21px] tracking-[0.01em]"
            style={{ fontFamily: "'Source Serif 4', serif" }}
          >
            Preview
          </h1>
          <div
            className="flex items-center gap-2"
            style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
          >
            {sampleText !== DEFAULT_TEXT && (
              <button
                onMouseEnter={() => setResetHover(true)}
                onMouseLeave={() => setResetHover(false)}
                onClick={() => {
                  setSampleText(DEFAULT_TEXT);
                  pushHistory();
                  setResetHover(false);
                }}
                className="relative z-10 cursor-pointer"
              >
                <img
                  src={resetSvg}
                  alt="Reset"
                  style={{ height: 15, width: 'auto' }}
                  draggable={false}
                />
                {resetHover && (
                  <span className="absolute left-full ml-2.5 top-1/2 -translate-y-1/2 text-[14px] text-[#aaa] whitespace-nowrap">
                    Reset to Sample Text
                  </span>
                )}
              </button>
            )}
            <img
              src={scaleSvg}
              alt="Scale"
              style={{ height: 13, width: 'auto', visibility: resetHover ? 'hidden' : 'visible' }}
              draggable={false}
            />
            <input
              type="range"
              min={MIN_FONT_SIZE}
              max={MAX_FONT_SIZE}
              step={1}
              value={previewFontSize}
              onChange={(e) => setPreviewFontSize(Number(e.target.value))}
              className="w-28"
              style={{ visibility: resetHover ? 'hidden' : 'visible' }}
            />
            <BaselineToggle visible={!resetHover} />
          </div>
        </div>
      </div>

      <textarea
        ref={hiddenRef}
        value={sampleText}
        onChange={handleChange}
        onSelect={syncCursor}
        onKeyDown={handleKeyDown}
        onKeyUp={syncCursor}
        onFocus={handleFocus}
        onBlur={handleBlur}
        tabIndex={-1}
        style={{
          position: 'fixed',
          width: 1,
          height: previewFontSize,
          opacity: 0,
          padding: 0,
          border: 'none',
          outline: 'none',
          resize: 'none',
          overflow: 'hidden',
          caretColor: 'transparent',
          fontSize: previewFontSize,
          zIndex: -1,
        }}
      />

      <div
        ref={containerRef}
        className={`flex-1 relative min-h-0 cursor-text select-none overflow-y-auto overflow-x-hidden ${window.electronAPI?.isScreenshotMode ? 'hide-scrollbar' : ''}`}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onContextMenu={async (e) => {
          e.preventDefault();
          isContextMenu.current = true;
          const action = await window.electronAPI.showPreviewContextMenu();
          isContextMenu.current = false;
          const ta = hiddenRef.current;
          if (!ta) return;
          ta.focus();
          if (action === 'cut') {
            document.execCommand('cut');
          } else if (action === 'copy') {
            document.execCommand('copy');
          } else if (action === 'paste') {
            document.execCommand('paste');
          } else if (action === 'selectAll') {
            ta.select();
            syncCursor();
          }
          draw();
        }}
      >
        {!hasAnyFont ? (
          <div className="absolute inset-0 flex items-center justify-center text-muted-foreground/40 text-sm">
            Load fonts to see preview
          </div>
        ) : (
          <canvas ref={canvasRef} className="block" style={{ opacity: cache ? 1 : 0 }} />
        )}
      </div>
    </div>
  );
};

function BaselineToggle({ visible }: { visible: boolean }) {
  const showBaseline = useMergeStore((s) => s.showBaseline);
  const setShowBaseline = useMergeStore((s) => s.setShowBaseline);

  return (
    <button
      type="button"
      role="switch"
      aria-checked={showBaseline}
      aria-label="Show baseline"
      onClick={() => setShowBaseline(!showBaseline)}
      className={`relative inline-flex h-4 w-7 shrink-0 cursor-pointer rounded-full transition-colors ${
        showBaseline ? 'bg-foreground' : 'bg-muted-foreground/30'
      }`}
      style={{ visibility: visible ? 'visible' : 'hidden' }}
    >
      <span
        className={`pointer-events-none inline-block h-3 w-3 rounded-full bg-background shadow-sm transition-transform ${
          showBaseline ? 'translate-x-3.5' : 'translate-x-0.5'
        }`}
        style={{ marginTop: 2 }}
      />
    </button>
  );
}
