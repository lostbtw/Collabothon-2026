import { Link, useLocation } from "react-router-dom";

/** Evidence links can point at views that later tickets build (matches, forecast, transactions, accounts). */
export function NotBuiltYet() {
  const { pathname, search } = useLocation();
  return (
    <div className="card stack">
      <h1>This view is not built yet</h1>
      <p className="muted">You followed a link to <code>{pathname + search}</code>. It will open the matching row once that screen exists.</p>
      <p><Link to="/">Back to the dashboard</Link></p>
    </div>
  );
}
