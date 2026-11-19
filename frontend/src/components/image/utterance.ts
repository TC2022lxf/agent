import type { NormRect, SlotKey, UtteranceBody } from '../../api/types'

/** The body the image canvas and the drawer both post. Region is omitted for a whole-image redo. */
export function buildImageUtterance(args: {
  text: string
  slot: string
  versionId: string
  region?: NormRect | null
  reasoning?: boolean
}): UtteranceBody {
  return {
    text: args.text,
    target_slot: args.slot as SlotKey,
    target_version_id: args.versionId,
    ...(args.region ? { target_region: args.region } : {}),
    reasoning: Boolean(args.reasoning),
  }
}
