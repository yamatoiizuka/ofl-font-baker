/**
 * @fileoverview Dialog component primitives wrapping Radix UI Dialog with styled overlay, content, header, and footer.
 */

import * as React from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { cn } from '@/renderer/lib/utils';
import modalCloseSvg from '@/renderer/assets/icons/modal-close.svg';

const Dialog = DialogPrimitive.Root;
const DialogTrigger = DialogPrimitive.Trigger;
const DialogClose = DialogPrimitive.Close;
const DialogPortal = DialogPrimitive.Portal;

/**
 * A semi-transparent backdrop overlay for dialog modals with fade animation.
 */
const DialogOverlay = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    forceMount
    className={cn(
      'fixed inset-0 z-[60] bg-black/40 dialog-overlay',
      className,
    )}
    style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
    {...props}
  />
));
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName;

/**
 * The main content container for a dialog, rendered in a portal with an overlay backdrop.
 */
const DialogContent = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
>(({ className, children, onPointerDownOutside, ...props }, ref) => (
  <DialogPortal>
    <DialogOverlay />
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 pointer-events-none">
      <DialogPrimitive.Content
        ref={ref}
        forceMount
        onPointerDownOutside={onPointerDownOutside}
        className="dialog-content relative w-full max-w-lg pointer-events-auto focus:outline-none"
        style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
        {...props}
      >
        <div
          className={cn(
            'w-full rounded-xl border border-border bg-background p-6 shadow-lg',
            className,
          )}
        >
          {children}
        </div>
        <DialogPrimitive.Close
          aria-label="Close"
          className="absolute -right-[40px] top-0 flex h-[30px] w-[30px] cursor-pointer items-center justify-center rounded-full bg-white pointer-events-auto"
          style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
        >
          <img src={modalCloseSvg} alt="" width={30} height={30} draggable={false} />
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </div>
  </DialogPortal>
));
DialogContent.displayName = DialogPrimitive.Content.displayName;

/**
 * A styled header section for dialog content with bottom margin.
 */
const DialogHeader: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ className, ...props }) => (
  <div className={cn('mb-4 py-1', className)} {...props} />
);

/**
 * A styled title component for dialog headers with semibold typography.
 */
const DialogTitle = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title ref={ref} className={cn('text-lg font-semibold', className)} {...props} />
));
DialogTitle.displayName = DialogPrimitive.Title.displayName;

export { Dialog, DialogTrigger, DialogContent, DialogHeader, DialogTitle, DialogClose };
