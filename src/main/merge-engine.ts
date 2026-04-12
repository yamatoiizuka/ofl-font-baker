/**
 * @fileoverview Font merge engine that resolves and spawns the PyInstaller-bundled or system Python merge executable.
 */

import { spawn } from 'child_process';
import path from 'path';
import fs from 'fs';
import { MergeConfig, MergeProgress, ExportManifest } from '@/shared/types';

/**
 * Resolve the merge engine executable path.
 *
 * Priority:
 * 1. Bundled PyInstaller binary in resources/ (standalone distribution)
 * 2. Python script via python3 (development)
 */
/**
 * Resolves the merge engine executable, preferring a bundled PyInstaller binary
 * and falling back to python3 with the script in development.
 * @returns An object with the command and arguments to spawn the merge engine.
 */
function resolveMergeEngine(): { command: string; args: string[] } {
  // In packaged app: resources are in app.getPath('exe')/../Resources/
  // In dev: resources are relative to dist/main/
  const possibleBinaryPaths = [
    // Packaged app (macOS .app bundle)
    path.join(process.resourcesPath || '', 'merge_fonts'),
    // Dev mode: from dist/main/ → ../../python/dist/merge_fonts
    path.join(__dirname, '../../python/dist/merge_fonts'),
  ];

  for (const binPath of possibleBinaryPaths) {
    try {
      fs.accessSync(binPath, fs.constants.X_OK);
      return { command: binPath, args: [] };
    } catch {
      // Not found or not executable, try next
    }
  }

  // Fallback: use python3 with the script
  const pythonScript = path.join(__dirname, '../../python/merge_fonts.py');
  return { command: 'python3', args: [pythonScript] };
}

/**
 * Spawns the merge engine subprocess, sends the merge config as JSON via stdin,
 * and streams progress updates from stderr.
 * @param config - The merge configuration specifying fonts, output path, and settings.
 * @param onProgress - Callback invoked with parsed progress updates from the engine.
 * @returns A promise resolving to the stdout output (typically the output file path).
 */
let activeProc: ReturnType<typeof spawn> | null = null;

/**
 * Kills the active merge subprocess if one is running.
 */
export function abortMerge(): void {
  if (activeProc) {
    activeProc.kill();
    activeProc = null;
  }
}

export function runMerge(
  config: MergeConfig,
  onProgress: (progress: MergeProgress) => void,
): Promise<ExportManifest> {
  abortMerge();
  return new Promise((resolve, reject) => {
    const { command, args } = resolveMergeEngine();

    const fontSource = (src: MergeConfig['base']) => ({
      path: src.path,
      familyName: src.familyName,
      styleName: src.styleName,
      isVariable: src.isVariable,
      scale: src.scale,
      baselineOffset: src.baselineOffset,
      axes: src.axes ?? [],
      copyright: src.copyright ?? '',
    });

    const pythonInput: Record<string, unknown> = {
      ...(config.latin ? { latin: fontSource(config.latin) } : {}),
      base: fontSource(config.base),
      outputDir: config.outputDir,
      outputFolderName: config.outputFolderName,
      overwrite: config.overwrite,
      outputFamilyName: config.outputFamilyName,
      outputWeight: config.outputWeight ?? 400,
      outputItalic: config.outputItalic ?? false,
      outputWidth: config.outputWidth ?? 5,
      outputDesigner: config.outputDesigner ?? '',
      outputCopyright: config.outputCopyright ?? '',
      outputUpm: config.outputUpm,
      ...(config.outputOptions ? { outputOptions: config.outputOptions } : {}),
    };

    const proc = spawn(command, args, {
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    activeProc = proc;

    let stdout = '';
    let stderr = '';

    proc.stdout.on('data', (data: Buffer) => {
      stdout += data.toString();
    });

    proc.stderr.on('data', (data: Buffer) => {
      const lines = data.toString().split('\n').filter(Boolean);
      for (const line of lines) {
        try {
          const progress: MergeProgress = JSON.parse(line);
          onProgress(progress);
        } catch {
          stderr += line + '\n';
        }
      }
    });

    proc.on('close', (code, signal) => {
      activeProc = null;
      if (code === 0) {
        try {
          const manifest: ExportManifest = JSON.parse(stdout.trim());
          resolve(manifest);
        } catch {
          reject(new Error(`Invalid manifest from merge engine: ${stdout}`));
        }
      } else if (signal) {
        reject(new Error('Export cancelled'));
      } else {
        reject(new Error(`Merge failed (exit code ${code}): ${stderr}`));
      }
    });

    proc.on('error', (err) => {
      reject(new Error(`Failed to spawn merge engine: ${err.message}`));
    });

    proc.stdin.write(JSON.stringify(pythonInput));
    proc.stdin.end();
  });
}
