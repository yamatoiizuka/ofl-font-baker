/**
 * @fileoverview HarfBuzz WASM text renderer with shape caching.
 *
 * Shaping (expensive) is cached and only re-run when text/font/axes change.
 * Geometry changes (scale/baseline) re-draw from cache using affine transforms.
 */

type HBModule = any;

let hbPromise: Promise<HBModule> | null = null;

/**
 * Lazily initializes and returns the HarfBuzz WASM module singleton.
 * @returns The initialized HarfBuzz module instance.
 */
async function getHB(): Promise<HBModule> {
  if (!hbPromise) {
    hbPromise = (async () => {
      const hbWasmUrl = (await import('harfbuzzjs/hb.wasm?url')).default;
      const createHarfBuzz = (await import('harfbuzzjs/hb.js')).default;
      const wasmModule = await createHarfBuzz({
        locateFile: (path: string) => (path.endsWith('.wasm') ? hbWasmUrl : path),
      });
      const hbjs = (await import('harfbuzzjs/hbjs.js')).default;
      return hbjs(wasmModule);
    })();
  }
  return hbPromise;
}

export interface FontHandle {
  hbBlob: any;
  hbFace: any;
  hbFont: any;
  upem: number;
  /** Set of Unicode codepoints covered by this font's cmap. */
  codepoints?: Set<number>;
}

/**
 * Creates a HarfBuzz font handle from a font binary buffer.
 * @param hb - The HarfBuzz WASM module instance.
 * @param fontBuffer - The raw font file data as an ArrayBuffer.
 * @param variations - Optional map of variation axis tags to values.
 * @returns A FontHandle containing the blob, face, font, and UPM.
 */
export async function createFontHandle(
  hb: HBModule,
  fontBuffer: ArrayBuffer,
  variations?: Record<string, number>,
): Promise<FontHandle> {
  const blob = hb.createBlob(new Uint8Array(fontBuffer));
  const face = hb.createFace(blob, 0);
  const font = hb.createFont(face);
  const upem = face.upem;
  if (variations && Object.keys(variations).length > 0) {
    font.setVariations(variations);
  }
  // Collect cmap codepoints for run splitting
  let codepoints: Set<number> | undefined;
  try {
    const collected = face.collectUnicodes();
    if (collected) codepoints = new Set(collected);
  } catch {
    // collectUnicodes may not be available in all harfbuzzjs builds
  }
  return { hbBlob: blob, hbFace: face, hbFont: font, upem, codepoints };
}

/**
 * Destroys a HarfBuzz font handle, releasing its WASM resources.
 * @param handle - The FontHandle to destroy.
 */
export function destroyFontHandle(handle: FontHandle) {
  handle.hbFont.destroy();
  handle.hbFace.destroy();
  handle.hbBlob.destroy();
}

// ---------------------------------------------------------------------------
// Cached shape data
// ---------------------------------------------------------------------------

/** A positioned glyph with its pre-parsed Path2D. */
interface CachedGlyph {
  path: Path2D;
  /** Glyph offset (dx) in normalized units (0..1 of base UPM). */
  dx: number;
  /** Glyph offset (dy) in normalized units. */
  dy: number;
  /** Advance width in normalized units. */
  advance: number;
  /** Which font group this glyph belongs to. */
  isLatin: boolean;
  /** 1 / font's own UPM — for converting glyph coords to normalized. */
  unitsScale: number;
  /** HarfBuzz glyph ID — 0 means .notdef (missing glyph). */
  glyphId: number;
}

interface CachedLine {
  glyphs: CachedGlyph[];
  /** Maps each glyph index to character index in sourceText. */
  charIndices?: number[];
  /** Original source text for this line (for kinsoku lookup). */
  sourceText?: string;
}

export interface ShapeCache {
  lines: CachedLine[];
  lineHeight: number;
  ascender: number;
  baseUpem: number;
  /** Number of characters per line (for cursor mapping). */
  charCounts: number[];
}

/** Pixel position of a character boundary (for cursor placement). */
export interface CharEdge {
  x: number;
  y: number; // baseline Y
  lineIndex: number;
  charIndex: number; // absolute index in the full text
}

/**
 * Fallback: determines whether a Unicode codepoint belongs to a Latin script range.
 * Used only when the font's cmap is unavailable.
 */
function isLatinCodepoint(cp: number): boolean {
  return (
    (cp >= 0x0000 && cp <= 0x024f) ||
    (cp >= 0x0250 && cp <= 0x02af) ||
    (cp >= 0x2000 && cp <= 0x22ff) ||
    (cp >= 0xfb00 && cp <= 0xfb06)
  );
}

interface RunInfo {
  text: string;
  handle: FontHandle;
  isLatin: boolean;
}

/**
 * Splits text into consecutive runs of Latin or non-Latin characters for shaping.
 * @param text - The input text string to split.
 * @param latHandle - The HarfBuzz font handle for Latin glyphs, or null.
 * @param jpHandle - The HarfBuzz font handle for Japanese glyphs, or null.
 * @returns An array of RunInfo objects, each representing a contiguous script run.
 */
function splitRuns(
  text: string,
  latHandle: FontHandle | null,
  jpHandle: FontHandle | null,
): RunInfo[] {
  const runs: RunInfo[] = [];
  if (!latHandle && !jpHandle) return runs;

  let chars: string[] = [];
  let isLat: boolean | null = null;

  function flush() {
    if (!chars.length || isLat === null) return;
    const handle = isLat && latHandle ? latHandle : (jpHandle ?? latHandle!);
    runs.push({
      text: chars.join(''),
      handle,
      isLatin: !!(isLat && latHandle),
    });
    chars = [];
  }

  for (const ch of text) {
    const cp = ch.codePointAt(0)!;
    // Use the Latin font's cmap to decide which font shapes each character.
    // Falls back to hardcoded Latin ranges if cmap is unavailable.
    const useEn =
      latHandle !== null &&
      (latHandle.codepoints ? latHandle.codepoints.has(cp) : isLatinCodepoint(cp));
    if (isLat !== null && useEn !== isLat) flush();
    isLat = useEn;
    chars.push(ch);
  }
  flush();
  return runs;
}

// --- Kinsoku (Japanese line-breaking rules) ---
// Characters that cannot start a line (closing punct, periods, etc.)
const NO_START = new Set(
  '、。，．・：；？！ー）」』】〕｝〉》≫…‥っゃゅょぁぃぅぇぉッャュョァィゥェォ々〻ヽヾゝゞ'
    .split('')
    .concat([',', '.', '!', '?', ')', ']', '}', '>', ';', ':']),
);
// Characters that cannot end a line (opening brackets, etc.)
const NO_END = new Set('（「『【〔｛〈《≪'.split('').concat(['(', '[', '{', '<']));

/**
 * Shape text and cache the results, with optional line wrapping.
 * maxWidth: available width in normalized units (pixels / fontSize).
 * If 0 or not given, no wrapping.
 */
export async function shapeText(
  text: string,
  latHandle: FontHandle | null,
  jpHandle: FontHandle | null,
): Promise<ShapeCache> {
  const hb = await getHB();
  const baseHandle = jpHandle ?? latHandle;
  if (!baseHandle)
    return {
      lines: [],
      lineHeight: 1000,
      ascender: 800,
      baseUpem: 1000,
      charCounts: [],
    };

  const extents = baseHandle.hbFont.hExtents;
  const ascender = extents?.ascender ?? baseHandle.upem * 0.88;
  const descender = extents?.descender ?? -(baseHandle.upem * 0.12);
  const lineGap = extents?.lineGap ?? baseHandle.upem * 0.1;
  const lineHeight = baseHandle.upem * 1.6;

  const pathCache = new Map<string, Path2D>();
  /**
   * Retrieves or creates a cached Path2D for a given glyph.
   * @param font - The HarfBuzz font object.
   * @param glyphId - The glyph ID to convert to a path.
   * @param fontKey - A string key identifying the font (for cache namespacing).
   * @returns The Path2D for the glyph.
   */
  function getPath(font: any, glyphId: number, fontKey: string): Path2D {
    const key = `${fontKey}:${glyphId}`;
    let p = pathCache.get(key);
    if (!p) {
      const svg = font.glyphToPath(glyphId);
      p = svg ? new Path2D(svg) : new Path2D();
      pathCache.set(key, p);
    }
    return p;
  }

  const lines: CachedLine[] = [];
  const inputLines = text.split('\n');

  for (const line of inputLines) {
    if (line.length === 0) {
      lines.push({ glyphs: [] });
      continue;
    }

    // Shape the entire line
    const runs = splitRuns(line, latHandle, jpHandle);
    const allGlyphs: CachedGlyph[] = [];
    // Map each glyph back to its source character index within the line
    const glyphCharIndices: number[] = [];
    let charIdx = 0;

    for (const run of runs) {
      const buffer = hb.createBuffer();
      buffer.addText(run.text);
      buffer.guessSegmentProperties();
      hb.shape(run.handle.hbFont, buffer);
      const shaped = buffer.json();
      buffer.destroy();

      const runUnitsScale = 1 / run.handle.upem;

      for (let i = 0; i < shaped.length; i++) {
        const g = shaped[i];
        allGlyphs.push({
          path: getPath(run.handle.hbFont, g.g, run.isLatin ? 'en' : 'jp'),
          dx: (g.dx || 0) * runUnitsScale,
          dy: (g.dy || 0) * runUnitsScale,
          advance: (g.ax || 0) * runUnitsScale,
          isLatin: run.isLatin,
          unitsScale: runUnitsScale,
          glyphId: g.g,
        });
        glyphCharIndices.push(charIdx + (g.cl ?? i));
      }
      charIdx += run.text.length;
    }

    lines.push({
      glyphs: allGlyphs,
      charIndices: glyphCharIndices,
      sourceText: line,
    });
  }

  const charCounts = text.split('\n').map((l) => l.length);
  return { lines, lineHeight, ascender, baseUpem: baseHandle.upem, charCounts };
}

export interface DrawOpts {
  fontSize: number;
  latScale: number;
  latBaseline: number;
  jpScale: number;
  jpBaseline: number;
  selStart?: number | null;
  selEnd?: number | null;
  showCursor?: boolean;
  paddingX?: number;
  paddingY?: number;
  canvasWidth?: number;
  /** Highlight glyphs belonging to this role in blue. */
  highlightRole?: 'latin' | 'base' | null;
  /** Draw a baseline guide line. */
  showBaseline?: boolean;
}

/**
 * Draw cached shape data onto a canvas. Returns character edge positions.
 */
export function drawCached(
  ctx: CanvasRenderingContext2D,
  cache: ShapeCache,
  opts: DrawOpts,
): CharEdge[] {
  const {
    fontSize,
    latScale,
    latBaseline,
    jpScale,
    jpBaseline,
    selStart,
    selEnd,
    showCursor,
    paddingX = 0,
    paddingY = 0,
    showBaseline,
    canvasWidth,
    highlightRole,
  } = opts;
  const pxPerBaseUnit = fontSize / cache.baseUpem;
  const lineHeightPx = cache.lineHeight * pxPerBaseUnit;
  const maxX = canvasWidth ? canvasWidth - paddingX : Infinity;
  const ascenderPx = cache.ascender * pxPerBaseUnit;
  let y = paddingY + ascenderPx;

  const hasSelection = selStart != null && selEnd != null && selStart !== selEnd;
  const selMin = hasSelection ? Math.min(selStart!, selEnd!) : -1;
  const selMax = hasSelection ? Math.max(selStart!, selEnd!) : -1;

  const edges: CharEdge[] = [];
  let absIdx = 0;
  let visualLine = 0;
  // Running start offset (in source characters) of the current source line
  // within the full text. Used to translate per-glyph cluster indices into
  // the character-space that the textarea's selection uses.
  let lineCharOffset = 0;

  /**
   * Draws a horizontal baseline guide line at the current y position.
   */
  function drawBaseline() {
    if (showBaseline) {
      ctx.save();
      ctx.strokeStyle =
        getComputedStyle(document.documentElement).getPropertyValue('--color-border').trim() ||
        'rgba(0, 0, 0, 0.2)';
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(ctx.canvas.width, y);
      ctx.stroke();
      ctx.restore();
    }
  }

  let cursorDrawn = false;
  /**
   * Draws the text cursor at the current selection end position if applicable.
   */
  function drawCursor() {
    if (showCursor && !hasSelection && selEnd != null && !cursorDrawn) {
      const lineTop = y - cache.ascender * pxPerBaseUnit;
      const edge = edges.find((e) => e.charIndex === selEnd && e.lineIndex === visualLine);
      if (edge) {
        ctx.save();
        ctx.fillRect(edge.x, lineTop, 1.5, lineHeightPx * 0.85);
        ctx.restore();
        cursorDrawn = true;
      }
    }
  }

  for (let li = 0; li < cache.lines.length; li++) {
    cursorDrawn = false;
    const line = cache.lines[li];
    const glyphs = line.glyphs;
    const charIndices = line.charIndices;
    const srcText = line.sourceText ?? '';
    let x = paddingX;

    drawBaseline();
    edges.push({ x, y, lineIndex: visualLine, charIndex: lineCharOffset });

    for (let gi = 0; gi < glyphs.length; gi++) {
      const g = glyphs[gi];
      const scale = g.isLatin ? latScale : jpScale;
      const advancePx = g.advance * fontSize * scale;

      // Line wrap: if adding this glyph exceeds maxX, start new visual line
      if (x + advancePx > maxX && x > paddingX) {
        // Kinsoku: check if current char can't start a line
        const ci = charIndices?.[gi];
        const ch = ci != null ? srcText[ci] : '';
        if (ch && NO_START.has(ch)) {
          // Keep this char on current line, break after
          drawGlyph(g, gi);
          drawCursor();
          y += lineHeightPx;
          visualLine++;
          x = paddingX;
          drawBaseline();
          edges.push({
            x,
            y,
            lineIndex: visualLine,
            charIndex: lineCharOffset + (charIndices?.[gi + 1] ?? srcText.length),
          });
          continue;
        }
        // Kinsoku: check if previous char can't end a line
        if (gi > 0) {
          const prevCi = charIndices?.[gi - 1];
          const prevCh = prevCi != null ? srcText[prevCi] : '';
          if (prevCh && NO_END.has(prevCh)) {
            // Just break here
          }
        }
        drawCursor();
        y += lineHeightPx;
        visualLine++;
        x = paddingX;
        drawBaseline();
        edges.push({
          x,
          y,
          lineIndex: visualLine,
          charIndex: lineCharOffset + (charIndices?.[gi] ?? gi),
        });
      }

      drawGlyph(g, gi);
    }

    /**
     * Renders a single glyph onto the canvas with selection highlighting and transforms.
     * @param g - The cached glyph data to draw.
     * @param _gi - The glyph index within the line (unused).
     */
    function drawGlyph(g: CachedGlyph, gi: number) {
      const scale = g.isLatin ? latScale : jpScale;
      const baseline = g.isLatin ? latBaseline : jpBaseline;
      const baselineOffsetPx = -(baseline * fontSize) / cache.baseUpem;
      let advancePx = g.advance * fontSize * scale;
      const lineTop = y - cache.ascender * pxPerBaseUnit;

      // Highlight based on the source character range this glyph covers,
      // not a per-glyph counter: Latin ligatures/contextual substitutions and
      // glyph decomposition can make glyph count diverge from char count, and
      // the textarea's selection indices are in char space.
      if (hasSelection) {
        const clusterStart =
          lineCharOffset + (charIndices?.[gi] ?? gi);
        const clusterEnd =
          lineCharOffset + (charIndices?.[gi + 1] ?? srcText.length);
        if (clusterEnd > selMin && clusterStart < selMax) {
          ctx.save();
          ctx.fillStyle = 'rgba(0, 120, 255, 0.18)';
          ctx.fillRect(x, lineTop, advancePx, lineHeightPx);
          ctx.restore();
        }
      }

      const gx = x + g.dx * fontSize * scale;
      const gy = y + baselineOffsetPx - g.dy * fontSize * scale;
      const glyphScale = fontSize * scale * g.unitsScale;

      // Highlight glyphs matching hovered role
      const isHighlighted =
        highlightRole != null &&
        ((highlightRole === 'latin' && g.isLatin) || (highlightRole === 'base' && !g.isLatin));

      // Add letter-spacing for tofu glyphs
      if (g.glyphId === 0) {
        advancePx += fontSize * scale * 0.1;
      }

      ctx.save();
      if (g.glyphId === 0) {
        ctx.globalAlpha = 0.1;
      } else if (isHighlighted) {
        const hl = getComputedStyle(document.documentElement)
          .getPropertyValue('--color-highlight')
          .trim();
        if (hl) ctx.fillStyle = hl;
      }
      ctx.translate(gx, gy);
      ctx.scale(glyphScale, -glyphScale);
      ctx.fill(g.path);
      ctx.restore();

      x += advancePx;
      absIdx++;
      edges.push({
        x,
        y,
        lineIndex: visualLine,
        charIndex: lineCharOffset + (charIndices?.[gi + 1] ?? srcText.length),
      });
    }

    drawCursor();
    absIdx++; // \n
    lineCharOffset += srcText.length + 1; // source chars in line + the newline
    y += lineHeightPx;
    visualLine++;
  }

  return edges;
}

/**
 * Find the nearest character position for a click at (px, py).
 */
export function hitTestClick(edges: CharEdge[], px: number, py: number): number {
  if (edges.length === 0) return 0;

  // Find which visual line was clicked by comparing y positions
  // Use the y values from edges themselves (most accurate)
  const lineYs = new Map<number, number>();
  for (const e of edges) {
    if (!lineYs.has(e.lineIndex)) lineYs.set(e.lineIndex, e.y);
  }

  let clickedLine = 0;
  let bestDist = Infinity;
  for (const [li, ly] of lineYs) {
    const dist = Math.abs(py - ly);
    if (dist < bestDist) {
      bestDist = dist;
      clickedLine = li;
    }
  }

  // Find nearest edge on that line
  const lineEdges = edges.filter((e) => e.lineIndex === clickedLine);
  if (lineEdges.length === 0) return 0;

  let nearest = lineEdges[0];
  let minDist = Math.abs(px - nearest.x);
  for (const e of lineEdges) {
    const dist = Math.abs(px - e.x);
    if (dist < minDist) {
      minDist = dist;
      nearest = e;
    }
  }

  return nearest.charIndex;
}

/**
 * Navigate cursor to the same x position on an adjacent line.
 */
export function navigateVertical(
  edges: CharEdge[],
  currentPos: number,
  direction: 'up' | 'down',
): number {
  const currentEdge = edges.find((e) => e.charIndex === currentPos);
  if (!currentEdge) return currentPos;

  const targetLine = currentEdge.lineIndex + (direction === 'up' ? -1 : 1);
  const maxVisualLine = Math.max(...edges.map((e) => e.lineIndex));
  if (targetLine < 0 || targetLine > maxVisualLine) return currentPos;

  const lineEdges = edges.filter((e) => e.lineIndex === targetLine);
  if (lineEdges.length === 0) return currentPos;

  let nearest = lineEdges[0];
  let minDist = Math.abs(currentEdge.x - nearest.x);
  for (const e of lineEdges) {
    const dist = Math.abs(currentEdge.x - e.x);
    if (dist < minDist) {
      minDist = dist;
      nearest = e;
    }
  }
  return nearest.charIndex;
}

export { getHB };
