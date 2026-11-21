import type { Recommendation } from "./types.gen";

/** The UI refuses to render a card without control level, execution mode, explanation and at least one evidence link. */
export function isRenderableRecommendation(r: Partial<Recommendation> | null | undefined): r is Recommendation {
  return Boolean(
    r &&
      r.control_level &&
      r.execution_mode &&
      r.explanation &&
      Array.isArray(r.explanation.why) &&
      Array.isArray(r.evidence) &&
      r.evidence.length > 0,
  );
}
