/**
 * @fileoverview Utility functions for merging Tailwind CSS class names using clsx and tailwind-merge.
 */

import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * Merges class names using clsx and tailwind-merge to resolve Tailwind CSS conflicts.
 * @param inputs - Class values to merge (strings, arrays, objects, etc.).
 * @returns The merged class name string.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
