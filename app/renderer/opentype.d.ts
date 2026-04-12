declare module 'opentype.js' {
  interface Font {
    names: {
      fontFamily: Record<string, string>;
      fontSubfamily: Record<string, string>;
      [key: string]: any;
    };
    unitsPerEm: number;
    numGlyphs: number;
    glyphs: { length: number; get(index: number): Glyph | null };
    charToGlyph(char: string): Glyph;
    tables: any;
  }

  interface Glyph {
    index: number;
    advanceWidth: number | undefined;
    getPath(x: number, y: number, fontSize: number): Path;
  }

  interface Path {
    fill: string | null;
    draw(ctx: CanvasRenderingContext2D): void;
  }

  function parse(buffer: ArrayBuffer): Font;

  export default { parse };
  export { Font, Glyph, Path };
}
