export function describeBridgeCaptureResult(result) {
  const sourceType = String(result?.source_type || "capture").replace(/_/g, " ");
  const qualityState = String(result?.quality_state || "unknown").replace(/_/g, " ");
  const trustTier = String(result?.trust_tier || "unknown").replace(/_/g, " ");
  if (result?.review_required) {
    return `Saved ${sourceType}. It is marked ${qualityState} with ${trustTier} trust and is now waiting in the review queue.`;
  }
  if (result?.quality_state === "user_artifact") {
    return `Saved ${sourceType}. It is stored as a user artifact with ${trustTier} trust and stays outside trusted memory by default.`;
  }
  return `Saved ${sourceType}. It is marked ${qualityState} with ${trustTier} trust and is available under the current Bridge trust rules.`;
}

export function describeBridgeReviewDecision(review, approved) {
  const title = String(review?.title || "capture");
  const trustTier = String(review?.trust_tier || "unknown");
  if (approved) {
    return `Approved ${title}. It now uses ${trustTier} trust and can participate in trusted reuse.`;
  }
  return `Kept ${title} gated. It remains outside trusted reuse until approved later.`;
}
