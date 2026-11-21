import { Link, useLocation } from "react-router-dom";

export function NotBuiltYet() {
  const { pathname, search } = useLocation();
  return (
    <div className="card stack">
      <h1>This page does not exist</h1>
      <p className="muted">Nothing is shown at <code>{pathname + search}</code>.</p>
      <p><Link to="/">Back to the Overview</Link></p>
    </div>
  );
}
