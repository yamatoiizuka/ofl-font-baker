/**
 * @fileoverview Utility for merging Tailwind CSS class names with tailwind-merge.
 */

import { twMerge, type ClassNameValue } from 'tailwind-merge';

/**
 * Joins class names (falsy values are skipped) and resolves Tailwind CSS conflicts,
 * letting later classes override earlier ones.
 * @param inputs - Class names, falsy values, or nested arrays of them.
 * @returns The merged class name string.
 */
export function cn(...inputs: ClassNameValue[]) {
  return twMerge(...inputs);
}
