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
  familyName: string;
  fontWeight: number;
  fontItalic: boolean;
  fontWidth: number;
  designer: string;
  copyright: string;
  upm: number;
}

export const DEFAULT_TEXT =
  '国LINE国Word国character国type国123国456国$1,789円国グーテンベルクが活版印刷術を発明したのは1440年代後半といわれています。それから約20年後の1465年、その新しい技術はアルプスを越え、イタリアに伝わりました。ドイツから来たSweynheimとPannartzという二人がローマの北にあるSubiacoという村の修道院に滞在し、そこでイタリア最初の印刷物をつくったのです。';

const INITIAL_UNDOABLE: UndoableState = {
  latinFont: null,
  baseFont: null,
  selectedRole: null,
  sampleText: DEFAULT_TEXT,
  familyName: 'Untitled Font',
  fontWeight: 400,
  fontItalic: false,
  fontWidth: 5,
  designer: '',
  copyright: '',
  upm: 1000,
};

// ---------------------------------------------------------------------------
// Full store interface
// ---------------------------------------------------------------------------

interface MergeState extends UndoableState {
  previewFontSize: number;
  showBaseline: boolean;
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
  setShowBaseline: (show: boolean) => void;
  updateFontAdjustment: (
    role: 'latin' | 'base',
    update: Partial<Pick<FontSource, 'baselineOffset' | 'scale'>>,
  ) => void;
  updateFontAxis: (role: 'latin' | 'base', tag: string, value: number) => void;
  setFamilyName: (name: string) => void;
  setFontWeight: (weight: number) => void;
  setFontItalic: (italic: boolean) => void;
  setFontWidth: (width: number) => void;
  setDesigner: (designer: string) => void;
  setCopyright: (copyright: string) => void;
  setUpm: (upm: number) => void;
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
    familyName: state.familyName,
    fontWeight: state.fontWeight,
    fontItalic: state.fontItalic,
    fontWidth: state.fontWidth,
    designer: state.designer,
    copyright: state.copyright,
    upm: state.upm,
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
      previewFontSize: 27,
      showBaseline: true,
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
          fontWeight: INITIAL_UNDOABLE.fontWeight,
          fontWidth: INITIAL_UNDOABLE.fontWidth,
          upm: INITIAL_UNDOABLE.upm,
          fontItalic: INITIAL_UNDOABLE.fontItalic,
        }));
        get().pushHistory();
      },

      setBaseFont: (font) => {
        set((state) => ({
          baseFont: font,
          selectedRole: font ? 'base' : state.latinFont ? 'latin' : null,
          fontWeight: INITIAL_UNDOABLE.fontWeight,
          fontWidth: INITIAL_UNDOABLE.fontWidth,
          upm: INITIAL_UNDOABLE.upm,
          fontItalic: INITIAL_UNDOABLE.fontItalic,
        }));
        get().pushHistory();
      },

      setSelectedRole: (role) => set({ selectedRole: role }),

      setSampleText: (text) => set({ sampleText: text }),
      setPreviewFontSize: (size) => set({ previewFontSize: size }),
      setShowBaseline: (show) => set({ showBaseline: show }),

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
      setFamilyName: (name) => set({ familyName: name }),
      setFontWeight: (weight) => {
        set({ fontWeight: weight });
        get().pushHistory();
      },
      setFontItalic: (italic) => {
        set({ fontItalic: italic });
        get().pushHistory();
      },
      setFontWidth: (width) => {
        set({ fontWidth: width });
        get().pushHistory();
      },
      setDesigner: (designer) => set({ designer: designer }),
      setCopyright: (copyright) => set({ copyright: copyright }),
      setUpm: (upm) => set({ upm: upm }),
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
      version: 6,
      partialize: (state) => ({
        latinFont: state.latinFont,
        baseFont: state.baseFont,
        sampleText: state.sampleText,
        previewFontSize: state.previewFontSize,
        familyName: state.familyName,
        fontWeight: state.fontWeight,
        fontItalic: state.fontItalic,
        fontWidth: state.fontWidth,
        designer: state.designer,
        copyright: state.copyright,
        upm: state.upm,
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
