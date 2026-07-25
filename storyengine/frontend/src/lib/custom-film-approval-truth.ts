export type DurableVideoPayload = {
  phase?: string | null;
  video_id?: string | null;
};

export type ApprovalSelectionRequest = {
  selections?: Record<string, unknown> | null;
};

export type ApprovalActionCard = {
  id: string;
  options?: readonly { value: string }[] | null;
};

/**
 * A video id alone is not evidence that paid production started. Custom Film
 * reserves its video before approval, while the durable conversation phase
 * advances to `created` only after approval has been recorded.
 */
export function durableCreatedVideoId(
  payload: DurableVideoPayload,
): string | null {
  return payload.phase === "created" && payload.video_id
    ? payload.video_id
    : null;
}

/**
 * Restore only the actionable approval card after a failed approval POST.
 * Other failed chat turns keep the existing generic error behavior.
 */
function isActionableCustomFilmApproval(
  card: ApprovalActionCard,
): boolean {
  return card.id === "custom_film_approval"
    && Boolean(card.options?.some((option) => option.value === "yes"));
}

export function failedCustomFilmApprovalCards<T extends ApprovalActionCard>(
  request: ApprovalSelectionRequest,
  priorCards: readonly T[] | null | undefined,
): T[] | undefined {
  if (
    request.selections?.custom_film_approval !== "yes"
    || !priorCards
  ) {
    return undefined;
  }
  const cards = priorCards.filter(
    isActionableCustomFilmApproval,
  );
  return cards.length > 0 ? cards : undefined;
}

/**
 * A resolved HTTP request may still report phase=plan when approval did not
 * durably advance. Prefer a replacement approval card returned by the server;
 * otherwise restore the prior actionable card instead of fabricating progress.
 */
export function resolvedCustomFilmApprovalCards<
  T extends ApprovalActionCard,
>(
  request: ApprovalSelectionRequest,
  response: {
    phase?: string | null;
    cards?: readonly T[] | null;
  },
  priorCards: readonly T[] | null | undefined,
): T[] | null | undefined {
  if (
    request.selections?.custom_film_approval !== "yes"
    || response.phase === "created"
  ) {
    return response.cards ? [...response.cards] : response.cards;
  }
  if (response.cards?.some(isActionableCustomFilmApproval)) {
    return [...response.cards];
  }
  return failedCustomFilmApprovalCards(request, priorCards)
    ?? (response.cards ? [...response.cards] : response.cards);
}
