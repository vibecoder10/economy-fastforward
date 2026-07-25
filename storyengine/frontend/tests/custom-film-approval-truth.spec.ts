import { expect, test } from "@playwright/test";
import {
  durableCreatedVideoId,
  failedCustomFilmApprovalCards,
  resolvedCustomFilmApprovalCards,
} from "../src/lib/custom-film-approval-truth";

test("a reserved video id cannot fabricate Building or an Open link", () => {
  expect(
    durableCreatedVideoId({
      phase: "plan",
      video_id: "reserved-before-approval",
    }),
  ).toBeNull();
  expect(
    durableCreatedVideoId({
      phase: "asking",
      video_id: "reserved-before-approval",
    }),
  ).toBeNull();
});

test("successful approval response and created-phase reload restore progress", () => {
  const durable = {
    phase: "created",
    video_id: "durably-approved-video",
  };
  expect(durableCreatedVideoId(durable)).toBe("durably-approved-video");
  expect(durableCreatedVideoId({ ...durable })).toBe(
    "durably-approved-video",
  );
});

test("failed approval restores only the actionable approval card", () => {
  const approval = {
    id: "custom_film_approval",
    label: "Approve paid production",
    options: [{ value: "yes" }, { value: "no" }],
  };
  const unrelated = { id: "length", label: "Length" };
  expect(
    failedCustomFilmApprovalCards(
      { selections: { custom_film_approval: "yes" } },
      [unrelated, approval],
    ),
  ).toEqual([approval]);
  expect(
    failedCustomFilmApprovalCards(
      { selections: { custom_film_approval: "no" } },
      [approval],
    ),
  ).toBeUndefined();
  expect(
    failedCustomFilmApprovalCards(
      { selections: { production_style: "cinematic" } },
      [approval],
    ),
  ).toBeUndefined();
});

test("resolved plan response restores prior approval and prefers server replacement", () => {
  const request = {
    selections: { custom_film_approval: "yes" },
  };
  const prior = {
    id: "custom_film_approval",
    label: "Approve original quote",
    options: [{ value: "yes" }, { value: "no" }],
  };
  expect(
    resolvedCustomFilmApprovalCards(
      request,
      { phase: "plan", cards: null },
      [prior],
    ),
  ).toEqual([prior]);

  const replacement = {
    id: "custom_film_approval",
    label: "Approve refreshed quote",
    options: [{ value: "yes" }, { value: "no" }],
  };
  expect(
    resolvedCustomFilmApprovalCards(
      request,
      { phase: "plan", cards: [replacement] },
      [prior],
    ),
  ).toEqual([replacement]);
  expect(
    resolvedCustomFilmApprovalCards(
      request,
      { phase: "created", cards: null },
      [prior],
    ),
  ).toBeNull();
});
