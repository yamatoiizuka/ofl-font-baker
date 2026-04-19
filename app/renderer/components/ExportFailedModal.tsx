/**
 * @fileoverview Modal shown when an export fails. Surfaces "Build Failed…"
 * prominently and offers a Copy Error shortcut so the full stderr text can
 * be pasted into a bug report without scraping the inline status.
 */

import React, { useEffect, useMemo, useState } from 'react';
import { Dialog, DialogContent, DialogTitle } from '@/renderer/components/ui/dialog';
import { Button } from '@/renderer/components/ui/button';
import { buildCopyableError } from '@/shared/error-format';
import { cn } from '@/renderer/lib/utils';
import failedSvg from '@/renderer/assets/icons/failed.svg';
import copySvg from '@/renderer/assets/icons/copy.svg';

interface Props {
  /** Full error message (Python traceback / stderr) available via "Copy Error". */
  error: string | null;
  /** Base font family name at merge time. Included in the copied payload. */
  baseFamily?: string;
  /** Sub (Latin / kana) font family name at merge time. Included in the copied payload. */
  subFamily?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const FAILED_COLOR = '#cf5e35';
const COPIED_FEEDBACK_MS = 2000;

/**
 * Failure confirmation modal shown after a merge error. The modal is kept
 * deliberately non-technical — there is no visible traceback or jargon —
 * but the Copy Error button yields a developer-friendly payload that
 * includes the font names the user was merging.
 */
export const ExportFailedModal: React.FC<Props> = ({
  error,
  baseFamily,
  subFamily,
  open,
  onOpenChange,
}) => {
  const [copied, setCopied] = useState(false);

  // Reset the "Copied" label when the modal is dismissed so the next
  // failure starts with the neutral label.
  useEffect(() => {
    if (!open) setCopied(false);
  }, [open]);

  // Redacted + dedup'd error plus a tiny font-name header so Issue
  // reports arrive with enough context to triage.
  const clipboardPayload = useMemo(
    () => (error ? buildCopyableError(error, { baseFamily, subFamily }) : ''),
    [error, baseFamily, subFamily],
  );

  const handleCopy = () => {
    if (!clipboardPayload) return;
    navigator.clipboard.writeText(clipboardPayload);
    setCopied(true);
    setTimeout(() => setCopied(false), COPIED_FEEDBACK_MS);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[280px] mx-auto p-[18px]" hideCloseButton>
        <div className="flex flex-col items-center text-center">
          <img
            src={failedSvg}
            alt=""
            width={100}
            height={64}
            draggable={false}
            className="mb-5 mt-5"
          />

          <DialogTitle className="text-[18px] font-normal" style={{ color: FAILED_COLOR }}>
            Build Failed...
          </DialogTitle>

          <div className="mt-7 mb-1 flex w-full flex-col items-center gap-3">
            <Button
              variant="secondary"
              onClick={() => onOpenChange(false)}
              className="w-full h-[40px] text-base shadow-none"
            >
              Close
            </Button>
            <button
              type="button"
              onClick={handleCopy}
              disabled={!clipboardPayload}
              className={cn(
                'inline-flex items-center gap-2 text-[14px] text-muted-foreground disabled:opacity-50 disabled:cursor-not-allowed',
                copied
                  ? 'cursor-default'
                  : 'cursor-pointer hover:text-foreground',
              )}
            >
              {copied ? (
                'Copied!'
              ) : (
                <>
                  <img src={copySvg} alt="" width={16} height={16} draggable={false} />
                  Copy Error
                </>
              )}
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};
