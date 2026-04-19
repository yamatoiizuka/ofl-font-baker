/**
 * @fileoverview Modal shown after a successful export. Pure acknowledgement —
 * Reveal-in-Finder is not offered here because the hand-off already happens
 * via the native Save panel's location, and adding it would compete with the
 * Close action for attention.
 */

import React from 'react';
import { Dialog, DialogContent, DialogTitle } from '@/renderer/components/ui/dialog';
import { Button } from '@/renderer/components/ui/button';
import { useMergeStore } from '@/renderer/stores/mergeStore';
import { computeStyleName } from '@/shared/constants';
import finishedSvg from '@/renderer/assets/icons/finished.svg';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Completion confirmation modal shown after a successful font export. Uses
 * the finished.svg check mark plus the family + style in the same typography
 * as the Metadata modal, followed by a single muted Close button.
 */
export const ExportCompleteModal: React.FC<Props> = ({ open, onOpenChange }) => {
  const { familyName, fontWeight, fontItalic, fontWidth } = useMergeStore();
  const styleName = computeStyleName(fontWeight, fontItalic, fontWidth);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[280px] mx-auto p-[18px]" hideCloseButton>
        <div className="flex flex-col items-center text-center">
          <img
            src={finishedSvg}
            alt=""
            width={54}
            height={54}
            draggable={false}
            className="mb-4 mt-2"
          />

          <DialogTitle className="text-[18px] font-semibold">
            {familyName || 'Untitled'}
            <span className="text-muted-foreground font-normal ml-2">{styleName}</span>
          </DialogTitle>

          <div className="text-[13px] text-green-500 mt-1 mb-8">Export Finished</div>

          <Button
            variant="secondary"
            onClick={() => onOpenChange(false)}
            className="w-full h-[40px] text-base shadow-none"
          >
            Close
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
};
