/**
 * @fileoverview React hook that manages the font merge workflow, including progress tracking and IPC communication.
 */

import { useEffect } from 'react';
import { useMergeStore } from '@/renderer/stores/mergeStore';
import { MergeConfig } from '@/shared/types';
import { computeFileStyleName } from '@/shared/constants';

/** Result of an attempted export. `cancelled` covers user-initiated aborts. */
export type MergeResult =
  | { kind: 'success'; path: string }
  | { kind: 'error'; error: string }
  | { kind: 'cancelled' };

/**
 * Hook that manages the font merge workflow, including progress tracking and IPC communication.
 * @returns An object with the startMerge function and the isMerging state.
 */
export function useMerge() {
  const setMergeProgress = useMergeStore((s) => s.setMergeProgress);
  const setIsMerging = useMergeStore((s) => s.setIsMerging);
  const isMerging = useMergeStore((s) => s.isMerging);

  // Listen for progress updates from main process
  useEffect(() => {
    const unsubscribe = window.electronAPI.onMergeProgress((progress) => {
      if (progress.stage === 'error') {
        // Errors are surfaced through the Failed modal; swallow the inline
        // progress event so the progress area doesn't flicker a red message
        // in parallel with the modal.
        setIsMerging(false);
        return;
      }
      if (!useMergeStore.getState().isMerging && progress.stage !== 'done') {
        setIsMerging(true);
      }
      setMergeProgress(progress);
      if (progress.stage === 'done') {
        setIsMerging(false);
      }
    });
    return () => {
      unsubscribe();
    };
  }, [setMergeProgress, setIsMerging]);

  /**
   * Initiates the font merge process by reading current store state, prompting for an output path,
   * and sending the merge configuration to the main process via IPC.
   * @returns A tagged result indicating success (with output path), a soft cancel, or an error.
   */
  async function startMerge(): Promise<MergeResult> {
    const {
      latinFont, baseFont, familyName, postScriptName, version,
      fontWeight, fontItalic, fontWidth,
      manufacturer, manufacturerURL,
      copyright, trademark, upm,
    } = useMergeStore.getState();

    if (!baseFont) {
      window.electronAPI.showAlert?.('No base font', 'Please load a base font first.');
      return { kind: 'cancelled' };
    }

    const fileStyle = computeFileStyleName(fontWeight, fontItalic, fontWidth);
    const defaultFolderName = `${familyName.replace(/\s+/g, '')}-${fileStyle}`;
    const chosenPath = await window.electronAPI.pickOutput(defaultFolderName);
    if (!chosenPath) return { kind: 'cancelled' };

    // Show the spinner immediately. The first "real" progress event only
    // arrives after the PyInstaller binary cold-starts and fontTools imports,
    // which can take several seconds — without this the user sees a dead UI.
    setIsMerging(true);
    setMergeProgress({ stage: 'loading', percent: 0, message: 'Starting...' });

    const config: MergeConfig = {
      subFont: latinFont,
      baseFont: baseFont!,
      output: {
        familyName,
        postScriptName,
        version,
        weight: fontWeight,
        italic: fontItalic,
        width: fontWidth,
        manufacturer,
        manufacturerURL,
        copyright,
        trademark,
        upm,
      },
      export: {
        package: {
          dir: chosenPath,
          overwrite: false,
        },
      },
    };

    const result = await window.electronAPI.startMerge(config);
    setIsMerging(false);
    if (!result.success) {
      return result.error === 'Export cancelled'
        ? { kind: 'cancelled' }
        : { kind: 'error', error: result.error };
    }
    return { kind: 'success', path: result.path ?? '' };
  }

  return { startMerge, isMerging };
}
