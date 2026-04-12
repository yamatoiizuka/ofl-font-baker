/**
 * @fileoverview Compact About modal showing app icon, name, version, and a GitHub link.
 *
 * Uses Radix Dialog primitives directly (rather than the shared DialogContent wrapper)
 * so this dialog can be narrower than the app-wide max-w-lg modal width without
 * affecting other modals.
 */

import React from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import iconUrl from '@/renderer/assets/icon.png';
import modalCloseSvg from '@/renderer/assets/icons/modal-close.svg';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const REPO = 'https://github.com/yamatoiizuka/ofl-font-baker';

/**
 * Compact About dialog: icon, name, version, GitHub link, copyright.
 */
export const AboutModal: React.FC<Props> = ({ open, onOpenChange }) => {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay
          forceMount
          className="fixed inset-0 z-[60] bg-black/40 dialog-overlay"
          style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
        />
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-2 pointer-events-none">
          <DialogPrimitive.Content
            forceMount
            onOpenAutoFocus={(e) => e.preventDefault()}
            className="dialog-content relative w-full max-w-[360px] pointer-events-auto focus:outline-none"
            style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
          >
            <DialogPrimitive.Title className="sr-only">About OFL Font Baker</DialogPrimitive.Title>
            <div className="w-full rounded-xl border border-border bg-background p-7 shadow-lg">
              <div className="flex flex-col items-center text-center">
                <img
                  src={iconUrl}
                  alt="OFL Font Baker"
                  className="w-[105px] h-[105px]"
                  draggable={false}
                />
                <h1 className="text-[22px] mt-4" style={{ fontFamily: "'Source Serif 4', serif" }}>
                  OFL Font Baker
                </h1>
                <div className="text-[12px] text-muted-foreground/70 mt-1">
                  Version {__APP_VERSION__}
                </div>

                <div className="flex items-center gap-4 mt-5">
                  <button
                    onClick={() => window.electronAPI.openExternal(REPO)}
                    className="text-[13px] text-blue-500 hover:underline cursor-pointer"
                  >
                    GitHub ↗
                  </button>
                  <button
                    onClick={() =>
                      window.electronAPI.openExternal('https://buymeacoffee.com/yamatoiizuka')
                    }
                    className="text-[13px] text-blue-500 hover:underline cursor-pointer"
                  >
                    Donate ↗
                  </button>
                </div>

                <div className="text-[11px] text-muted-foreground/60 mt-5">
                  © {new Date().getFullYear()} Yamato Iizuka · AGPL-3.0
                </div>
              </div>
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
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
};
