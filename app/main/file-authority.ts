import fs from 'fs';
import path from 'path';
import os from 'os';

const MAX_FONT_BYTES = 256 * 1024 * 1024;
type Identity = { dev: number; ino: number };
type Destination = { path: string; identity: Identity | null; mtimeMs: number | null };
const same = (a: Identity, b: Identity) => a.dev === b.dev && a.ino === b.ino;

/** Main-owned grants, never reconstructed from renderer/localStorage paths. */
export class FileAuthority {
  private inputs = new Map<string, Identity>();
  private output: Destination | null = null;

  constructor(private registry: string) {
    try {
      const entries = JSON.parse(fs.readFileSync(registry, 'utf8'));
      if (Array.isArray(entries)) {
        for (const [name, identity] of entries) {
          if (typeof name === 'string' && Number.isFinite(identity?.dev) && Number.isFinite(identity?.ino)) {
            this.inputs.set(name, identity);
          }
        }
      }
    } catch { /* First run or invalid registry: require native selection again. */ }
  }

  private font(file: unknown) {
    if (typeof file !== 'string' || !path.isAbsolute(file) || !/\.(otf|ttf)$/i.test(file)) {
      throw new Error('Select an OpenType or TrueType font');
    }
    const canonical = fs.realpathSync(file);
    const stat = fs.statSync(canonical);
    if (!stat.isFile() || stat.size > MAX_FONT_BYTES) throw new Error('Invalid or oversized font');
    return { canonical, stat };
  }

  grantInput(file: string): string {
    const { canonical, stat } = this.font(file);
    this.inputs.set(canonical, { dev: stat.dev, ino: stat.ino });
    fs.mkdirSync(path.dirname(this.registry), { recursive: true });
    const temporary = this.registry + '.tmp';
    fs.writeFileSync(temporary, JSON.stringify([...this.inputs]), { mode: 0o600 });
    fs.renameSync(temporary, this.registry);
    return canonical;
  }

  requireInput(file: unknown): string {
    const { canonical, stat } = this.font(file);
    const grant = this.inputs.get(canonical);
    if (!grant || !same(grant, stat)) throw new Error('Please select this font again to allow access');
    return canonical;
  }

  readInput(file: unknown): Buffer {
    const canonical = this.requireInput(file);
    const fd = fs.openSync(canonical, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
    try {
      const stat = fs.fstatSync(fd);
      if (!stat.isFile() || stat.size > MAX_FONT_BYTES || !same(stat, this.inputs.get(canonical)!)) {
        throw new Error('Font changed; please select it again');
      }
      return fs.readFileSync(fd);
    } finally { fs.closeSync(fd); }
  }

  hasInput(file: unknown): boolean {
    try { this.requireInput(file); return true; } catch { return false; }
  }

  clearOutput(): void { this.output = null; }

  grantOutput(file: string): string {
    this.output = null;
    const selected = path.resolve(file);
    const canonical = path.join(fs.realpathSync(path.dirname(selected)), path.basename(selected));
    if (canonical === path.parse(canonical).root || canonical === fs.realpathSync(os.homedir())) {
      throw new Error('Choose a dedicated export folder');
    }
    const stat = fs.existsSync(canonical) ? fs.lstatSync(canonical) : null;
    if (stat && (!stat.isDirectory() || stat.isSymbolicLink())) throw new Error('Choose a regular export folder');
    this.output = { path: canonical, identity: stat && { dev: stat.dev, ino: stat.ino }, mtimeMs: stat?.mtimeMs ?? null };
    return canonical;
  }

  consumeOutput(file: unknown, inputs: string[]): { dir: string; overwrite: boolean } {
    const grant = this.output;
    this.output = null; // Every attempt consumes the native dialog authorization.
    if (!grant || file !== grant.path) throw new Error('Choose the export folder again');
    // Resolve the parent again so a replaced parent symlink cannot redirect export.
    if (path.join(fs.realpathSync(path.dirname(grant.path)), path.basename(grant.path)) !== grant.path) {
      throw new Error('Export location changed; choose it again');
    }
    const stat = fs.existsSync(grant.path) ? fs.lstatSync(grant.path) : null;
    if (!!stat !== !!grant.identity || (stat && grant.identity &&
      (!stat.isDirectory() || stat.isSymbolicLink() || !same(stat, grant.identity) || stat.mtimeMs !== grant.mtimeMs))) {
      throw new Error('Export folder changed; choose it again');
    }
    for (const input of inputs) {
      const relative = path.relative(grant.path, input);
      if (!relative || (!relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative))) {
        throw new Error('Export folder must not contain an input font');
      }
    }
    return { dir: grant.path, overwrite: !!grant.identity };
  }
}
