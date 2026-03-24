/**
 * One full example rhino description (4 parts) for IndivAID / schema.
 * Used as placeholder/example in "General description" UI.
 */
export const EXAMPLE_RHINO_DESCRIPTION = {
  left_ear: 'edge intact; 1 notch(es); top; central_hole none; tuft present',
  right_ear: 'edge torn; central_hole round_middle; mid; tuft absent',
  head: 'side_left; horn long sharp; muzzle round; wrinkles medium',
  body: 'full; medium; smooth',
} as const;

export const DESCRIPTION_PART_LABELS: Record<keyof typeof EXAMPLE_RHINO_DESCRIPTION, string> = {
  left_ear: 'Left ear',
  right_ear: 'Right ear',
  head: 'Head',
  body: 'Body',
};
