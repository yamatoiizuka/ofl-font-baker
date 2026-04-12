/**
 * @fileoverview React hook that manages the font merge workflow, including progress tracking and IPC communication.
 */

import { useEffect } from 'react';
import { useMergeStore } from '@/renderer/stores/mergeStore';
import { MergeConfig } from '@/shared/types';
import { computeFileStyleName } from '@/shared/constants';

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
      if (!useMergeStore.getState().isMerging && progress.stage !== 'done' && progress.stage !== 'error') {
        setIsMerging(true);
      }
      setMergeProgress(progress);
      if (progress.stage === 'done' || progress.stage === 'error') {
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
   */
  async function startMerge() {
    const {
      latinFont, baseFont, outputFamilyName,
      outputWeight, outputItalic, outputWidth,
      outputDesigner, outputCopyright, outputUpm,
    } = useMergeStore.getState();

    if (!baseFont) {
      window.electronAPI.showAlert?.('No base font', 'Please load a base font first.');
      return;
    }

    const fileStyle = computeFileStyleName(outputWeight, outputItalic, outputWidth);
    const defaultFolderName = `${outputFamilyName.replace(/\s+/g, '')}-${fileStyle}`;
    const chosenPath = await window.electronAPI.pickOutput(defaultFolderName);
    if (!chosenPath) return;
    // Save dialog returns the full target path; split into parent dir + folder name.
    const sep = chosenPath.lastIndexOf('/');
    const outputDir = sep >= 0 ? chosenPath.slice(0, sep) : chosenPath;
    const folderName = sep >= 0 ? chosenPath.slice(sep + 1) : chosenPath;

    // Show the spinner immediately. The first "real" progress event only
    // arrives after the PyInstaller binary cold-starts and fontTools imports,
    // which can take several seconds — without this the user sees a dead UI.
    setIsMerging(true);
    setMergeProgress({ stage: 'loading', percent: 0, message: 'Starting...' });

    const config: MergeConfig = {
      latin: latinFont,
      base: baseFont!,
      outputDir,
      outputFolderName: folderName,
      overwrite: false,
      outputFamilyName,
      outputWeight,
      outputItalic,
      outputWidth,
      outputDesigner,
      outputCopyright,
      outputUpm,
    };

    const result = await window.electronAPI.startMerge(config);
    if (!result.success) {
      if (result.error !== 'Export cancelled') {
        setMergeProgress({ stage: 'error', percent: 0, message: result.error });
      }
      setIsMerging(false);
      return;
    }
  }

  return { startMerge, isMerging };
}
