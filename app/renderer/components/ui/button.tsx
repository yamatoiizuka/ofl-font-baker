/**
 * @fileoverview Reusable Button component with a few style variants and sizes.
 */

import * as React from 'react';
import { cn } from '@/renderer/lib/utils';

const BASE_CLASS =
  'inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 cursor-pointer';

const VARIANT_CLASSES = {
  default: 'bg-primary text-primary-foreground shadow hover:bg-primary/90',
  outline:
    'border border-input bg-background shadow-sm hover:bg-secondary hover:text-secondary-foreground',
  secondary: 'bg-secondary text-secondary-foreground shadow-sm hover:bg-secondary/80',
  ghost: 'hover:bg-secondary hover:text-secondary-foreground',
} as const;

const SIZE_CLASSES = {
  default: 'h-9 px-4 py-2',
  sm: 'h-8 rounded-md px-3 text-xs',
  lg: 'h-10 rounded-md px-8',
  icon: 'h-9 w-9',
} as const;

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: keyof typeof VARIANT_CLASSES;
  size?: keyof typeof SIZE_CLASSES;
}

/**
 * A styled button component with variant and size support.
 */
const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'default', size = 'default', ...props }, ref) => {
    return (
      <button
        className={cn(BASE_CLASS, VARIANT_CLASSES[variant], SIZE_CLASSES[size], className)}
        ref={ref}
        {...props}
      />
    );
  },
);
Button.displayName = 'Button';

export { Button };
