"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2, TriangleAlert } from "lucide-react";
import { getCustomFilmRecipes, type CustomFilmRecipe } from "@/lib/api";

/**
 * "Your saved styles" section of the Director home screen (Chunk 1.D).
 * Mirrors director-mockup/index.html `#home` `.sec` for saved styles
 * (~L683-696) — the mockup ships as a permanent empty state because zero
 * recipes have ever been saved in production, but this component still
 * handles loading/error/populated so it doesn't lie the first time someone
 * does save one.
 *
 * A "recipe" is created from inside a video via the canvas's gold "Lock
 * this as a style" action — not from this screen. There is no `last_used_at`
 * field on the recipe row and no `videos.recipe_id` column; this component
 * must never display or infer one.
 */
export function StyleLibrary() {
  const { data, status, fetchStatus } = useQuery({
    queryKey: ["custom-film-recipes"],
    queryFn: getCustomFilmRecipes,
    staleTime: 60 * 1000,
  });

  // Deliberately NOT `isLoading`/`isError` (TanStack Query v5 shorthands).
  // `isLoading` = `isPending && isFetching`, which is FALSE while a query
  // sits in `fetchStatus: "paused"` (react-query's own networkMode:"online"
  // pause — it enters this state whenever a fetch fails while the browser
  // is/was considered offline, and stays there without ever flipping to
  // `status: "error"`). With the old isLoading/isError checks, a paused
  // query fell straight through to the "0 saved" empty-state branch below
  // — a real API failure rendering as "you have no styles", exactly the lie
  // this section must never tell. Found live: this endpoint 404s in this
  // checkout (chunk 1.B's route isn't deployed here yet) and reliably lands
  // in the paused state in the verification browser. `status` and
  // `fetchStatus` don't have this gap — every branch below is reachable and
  // mutually exclusive.
  const isPending = status === "pending";
  const isFetchingNow = fetchStatus === "fetching";
  const isPaused = fetchStatus === "paused";
  const isErrorState = status === "error";
  const isSuccess = status === "success";

  const recipes = data?.recipes ?? [];
  const count = data?.recipes.length ?? 0;

  return (
    <div className="mb-11">
      <div className="mb-3.5 flex items-baseline justify-between">
        <h2 className="text-base font-semibold tracking-tight text-ink">Your saved styles</h2>
        <span className="text-[12.5px] text-faint">
          {isSuccess ? `${count} saved` : isErrorState || isPaused ? "Couldn't load" : "Loading…"}
        </span>
      </div>

      {isPending && isFetchingNow && (
        <div className="flex items-center justify-center gap-2 rounded-card border border-line-soft bg-surface px-4 py-10 text-xs text-dim">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Loading your saved styles…
        </div>
      )}

      {/* An API failure must not be mistaken for "you have no styles yet" —
          that would be a lie. This is a visibly different, red-bordered
          state, not the gold empty state below. Covers BOTH a settled error
          (`status: "error"`) and the paused-offline limbo above. */}
      {(isErrorState || (isPending && isPaused)) && (
        <div
          role="alert"
          className="flex items-start gap-3 rounded-card border border-red/30 bg-red/[0.05] px-5 py-4 text-sm text-dim"
        >
          <TriangleAlert className="mt-0.5 h-4 w-4 flex-none text-red" strokeWidth={1.75} />
          <div>
            <p className="font-medium text-ink">Couldn&apos;t load your saved styles</p>
            <p className="mt-1 text-[12.5px] leading-relaxed text-faint">
              This is a loading problem, not an empty library — your styles (if you have
              any) are still there. Refresh the page to try again.
            </p>
          </div>
        </div>
      )}

      {isSuccess && recipes.length === 0 && (
        <div className="flex gap-6 rounded-card border border-dashed border-gold-director/30 bg-gradient-to-b from-gold-director/[0.045] to-transparent p-7">
          <div className="flex h-[46px] w-[46px] flex-none items-center justify-center rounded-[13px] border border-gold-director/30 bg-gold-director/[0.12] text-xl text-gold-director">
            ★
          </div>
          <div>
            <h3 className="mb-1.5 text-[15px] font-semibold text-ink">
              You haven&apos;t saved a style yet
            </h3>
            <p className="mb-2 max-w-[620px] text-[13px] leading-relaxed text-dim">
              A style is a finished look you liked, frozen so you can reuse it — how it&apos;s
              built, how it&apos;s written, how it looks, and how much you chose to spend, all
              in one. Save one and it shows up here as a one-click starting point, exactly
              like the four cards at the top of this page.
            </p>
            <p className="max-w-[620px] text-[13px] leading-relaxed text-faint">
              You save one from inside a video: hit{" "}
              <b className="font-semibold text-gold-director">Lock this as a style</b> on the
              canvas when a video is looking the way you want.
            </p>
          </div>
        </div>
      )}

      {isSuccess && recipes.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {recipes.map((recipe) => (
            <SavedStyleCard key={recipe.id} recipe={recipe} />
          ))}
        </div>
      )}
    </div>
  );
}

function SavedStyleCard({ recipe }: { recipe: CustomFilmRecipe }) {
  return (
    <div className="flex flex-col rounded-card border border-edge bg-surface p-4">
      <h3 className="text-[14.5px] font-semibold text-ink">{recipe.name}</h3>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {recipe.section_mix.map((section) => (
          <span
            key={section.role}
            className="rounded-[7px] border border-line-soft bg-white/[0.03] px-2 py-1 text-[11px] text-dim"
          >
            {section.role} · {Math.round(section.share * 100)}%
          </span>
        ))}
      </div>
      <button
        type="button"
        disabled
        title="Not available yet"
        // Not wired — reusing a saved recipe to start a new video is a
        // creation flow outside this chunk's scope (this path is currently
        // unreachable: recipes.length is always 0 in production today).
        // Visibly disabled rather than active-looking, per the "no dead
        // buttons" rule — even though it's unreachable today, it must never
        // render as clickable if a recipe ever IS saved.
        className="mt-3 inline-flex w-fit items-center gap-1.5 self-start text-[11.5px] font-semibold text-faint disabled:cursor-not-allowed"
      >
        Use this <span className="text-[10px] uppercase tracking-wide">&middot; coming soon</span>
      </button>
    </div>
  );
}
