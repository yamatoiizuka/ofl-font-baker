/**
 * @fileoverview Zustand store managing global application state for font sources, merge settings, and UI selection.
 * Includes undo/redo history for all user-visible state changes.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { FontSource, MergeProgress } from '@/shared/types';

// ---------------------------------------------------------------------------
// Undoable state (tracked in history)
// ---------------------------------------------------------------------------

interface UndoableState {
  latinFont: FontSource | null;
  baseFont: FontSource | null;
  selectedRole: 'latin' | 'base' | null;
  sampleText: string;
  previewFontSize: number;
  outputFamilyName: string;
  outputWeight: number;
  outputItalic: boolean;
  outputWidth: number;
  outputDesigner: string;
  outputCopyright: string;
  outputUpm: number;
}

export const DEFAULT_TEXT =
  '国LINE国Word国character国type国123国456国$1,789円国グーテンベルクが活版印刷術を発明したのは1440年代後半といわれています。それから約20年後の1465年、その新しい技術はアルプスを越え、イタリアに伝わりました。ドイツから来たSweynheimとPannartzという二人がローマの北にあるSubiacoという村の修道院に滞在し、そこでイタリア最初の印刷物をつくったのです。';

const INITIAL_UNDOABLE: UndoableState = {
  latinFont: null,
  baseFont: null,
  selectedRole: null,
  sampleText: DEFAULT_TEXT,
  previewFontSize: 27,
  outputFamilyName: 'Untitled Font',
  outputWeight: 400,
  outputItalic: false,
  outputWidth: 5,
  outputDesigner: '',
  outputCopyright: '',
  outputUpm: 1000,
};

// ---------------------------------------------------------------------------
// Full store interface
// ---------------------------------------------------------------------------

interface MergeState extends UndoableState {
  hoveredRole: 'latin' | 'base' | null;
  mergeProgress: MergeProgress | null;
  isMerging: boolean;

  // History
  _history: UndoableState[];
  _historyIndex: number;
  _skipHistory: boolean;

  setHoveredRole: (role: 'latin' | 'base' | null) => void;
  setLatinFont: (font: FontSource | null) => void;
  setBaseFont: (font: FontSource | null) => void;
  setSelectedRole: (role: 'latin' | 'base' | null) => void;
  setSampleText: (text: string) => void;
  setPreviewFontSize: (size: number) => void;
  updateFontAdjustment: (
    role: 'latin' | 'base',
    update: Partial<Pick<FontSource, 'baselineOffset' | 'scale'>>,
  ) => void;
  updateFontAxis: (role: 'latin' | 'base', tag: string, value: number) => void;
  setOutputFamilyName: (name: string) => void;
  setOutputWeight: (weight: number) => void;
  setOutputItalic: (italic: boolean) => void;
  setOutputWidth: (width: number) => void;
  setOutputDesigner: (designer: string) => void;
  setOutputCopyright: (copyright: string) => void;
  setOutputUpm: (upm: number) => void;
  setMergeProgress: (progress: MergeProgress | null) => void;
  setIsMerging: (merging: boolean) => void;
  /** Push current state to history (call after slider release, text blur, etc.) */
  pushHistory: () => void;
  undo: () => void;
  redo: () => void;
  reset: () => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const MAX_HISTORY = 100;

function extractUndoable(state: MergeState): UndoableState {
  return {
    latinFont: state.latinFont,
    baseFont: state.baseFont,
    selectedRole: state.selectedRole,
    sampleText: state.sampleText,
    previewFontSize: state.previewFontSize,
    outputFamilyName: state.outputFamilyName,
    outputWeight: state.outputWeight,
    outputItalic: state.outputItalic,
    outputWidth: state.outputWidth,
    outputDesigner: state.outputDesigner,
    outputCopyright: state.outputCopyright,
    outputUpm: state.outputUpm,
  };
}

function statesEqual(a: UndoableState, b: UndoableState): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useMergeStore = create<MergeState>()(
  persist(
    (set, get) => ({
      ...INITIAL_UNDOABLE,
      hoveredRole: null,
      mergeProgress: null,
      isMerging: false,
      _history: [INITIAL_UNDOABLE],
      _historyIndex: 0,
      _skipHistory: false,

      setHoveredRole: (role) => set({ hoveredRole: role }),

      setLatinFont: (font) => {
        set((state) => ({
          latinFont: font,
          selectedRole: font ? 'latin' : state.baseFont ? 'base' : null,
          outputWeight: INITIAL_UNDOABLE.outputWeight,
          outputWidth: INITIAL_UNDOABLE.outputWidth,
          outputUpm: INITIAL_UNDOABLE.outputUpm,
          outputItalic: INITIAL_UNDOABLE.outputItalic,
        }));
        get().pushHistory();
      },

      setBaseFont: (font) => {
        set((state) => ({
          baseFont: font,
          selectedRole: font ? 'base' : state.latinFont ? 'latin' : null,
          outputWeight: INITIAL_UNDOABLE.outputWeight,
          outputWidth: INITIAL_UNDOABLE.outputWidth,
          outputUpm: INITIAL_UNDOABLE.outputUpm,
          outputItalic: INITIAL_UNDOABLE.outputItalic,
        }));
        get().pushHistory();
      },

      setSelectedRole: (role) => set({ selectedRole: role }),

      setSampleText: (text) => set({ sampleText: text }),
      setPreviewFontSize: (size) => set({ previewFontSize: size }),

      updateFontAdjustment: (role, update) =>
        set((state) => {
          const key = role === 'latin' ? 'latinFont' : 'baseFont';
          const font = state[key];
          return { [key]: font ? { ...font, ...update } : null };
        }),

      updateFontAxis: (role, tag, value) =>
        set((state) => {
          const key = role === 'latin' ? 'latinFont' : 'baseFont';
          const font = state[key];
          return {
            [key]: font
              ? {
                  ...font,
                  axes: font.axes.map((a) => (a.tag === tag ? { ...a, currentValue: value } : a)),
                }
              : null,
          };
        }),

      // Text setters don't push history per keystroke — components call
      // pushHistory() on blur to record one snapshot per edit session.
      setOutputFamilyName: (name) => set({ outputFamilyName: name }),
      setOutputWeight: (weight) => {
        set({ outputWeight: weight });
        get().pushHistory();
      },
      setOutputItalic: (italic) => {
        set({ outputItalic: italic });
        get().pushHistory();
      },
      setOutputWidth: (width) => {
        set({ outputWidth: width });
        get().pushHistory();
      },
      setOutputDesigner: (designer) => set({ outputDesigner: designer }),
      setOutputCopyright: (copyright) => set({ outputCopyright: copyright }),
      setOutputUpm: (upm) => set({ outputUpm: upm }),
      setMergeProgress: (progress) => set({ mergeProgress: progress }),
      setIsMerging: (merging) => set({ isMerging: merging }),

      pushHistory: () => {
        const state = get();
        if (state._skipHistory) return;
        const current = extractUndoable(state);
        const lastInHistory = state._history[state._historyIndex];
        if (lastInHistory && statesEqual(current, lastInHistory)) return;

        const newHistory = state._history.slice(0, state._historyIndex + 1);
        newHistory.push(current);
        if (newHistory.length > MAX_HISTORY) newHistory.shift();

        set({
          _history: newHistory,
          _historyIndex: newHistory.length - 1,
        });
      },

      undo: () => {
        const state = get();
        if (state._historyIndex <= 0) return;
        const newIndex = state._historyIndex - 1;
        const snapshot = state._history[newIndex];
        set({ ...snapshot, _historyIndex: newIndex, _skipHistory: true });
        set({ _skipHistory: false });
      },

      redo: () => {
        const state = get();
        if (state._historyIndex >= state._history.length - 1) return;
        const newIndex = state._historyIndex + 1;
        const snapshot = state._history[newIndex];
        set({ ...snapshot, _historyIndex: newIndex, _skipHistory: true });
        set({ _skipHistory: false });
      },

      reset: () => {
        set({
          ...INITIAL_UNDOABLE,
          mergeProgress: null,
          isMerging: false,
          _history: [INITIAL_UNDOABLE],
          _historyIndex: 0,
        });
      },
    }),
    {
      name: 'ofl-font-baker-store',
      version: 5,
      partialize: (state) => ({
        latinFont: state.latinFont,
        baseFont: state.baseFont,
        sampleText: state.sampleText,
        previewFontSize: state.previewFontSize,
        outputFamilyName: state.outputFamilyName,
        outputWeight: state.outputWeight,
        outputItalic: state.outputItalic,
        outputWidth: state.outputWidth,
        outputDesigner: state.outputDesigner,
        outputCopyright: state.outputCopyright,
        outputUpm: state.outputUpm,
      }),
      onRehydrateStorage: () => (state) => {
        if (!state) return;
        if (state.baseFont) state.selectedRole = 'base';
        else if (state.latinFont) state.selectedRole = 'latin';
        // Initialize history from rehydrated state
        const snapshot = extractUndoable(state);
        state._history = [snapshot];
        state._historyIndex = 0;
      },
    },
  ),
);
