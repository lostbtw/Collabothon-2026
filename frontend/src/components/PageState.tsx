import type { ReactNode } from "react";
import type { Loadable } from "../lib/useApi";

/** Shared loading / error / empty handling so every page behaves the same. */
/** `keepWhileLoading`: on a re-read, keep showing the data already on screen instead of the loading text. */
export function PageState<T>({ state, empty, keepWhileLoading, children }: { state: Loadable<T>; empty?: (data: T) => boolean; keepWhileLoading?: boolean; children: (data: T) => ReactNode }) {
  if (state.loading && !(keepWhileLoading && state.data !== null)) return <p className="muted">Loading…</p>;
  if (state.error) return <p className="danger" role="alert">Could not load this page: {state.error}</p>;
  if (state.data === null || empty?.(state.data)) return <p className="muted">Nothing here yet.</p>;
  return <>{children(state.data)}</>;
}
