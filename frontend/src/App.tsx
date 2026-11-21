import { Navigate, Route, Routes, useParams } from "react-router-dom";
import { Layout } from "./components/Layout";
import { CompanyProvider } from "./lib/company";
import { Activity } from "./pages/Activity";
import { DocumentDetail } from "./pages/Documents";
import { Money } from "./pages/Money";
import { NotBuiltYet } from "./pages/NotBuiltYet";
import { Overview } from "./pages/Overview";
import { MatchRedirect } from "./pages/Redirects";
import { Settings } from "./pages/Settings";
import { Todo } from "./pages/Todo";

function To({ path }: { path: (p: Record<string, string | undefined>) => string }) {
  return <Navigate to={path(useParams())} replace />;
}

export function App() {
  return (
    <CompanyProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Overview />} />
          <Route path="money" element={<Money />} />
          <Route path="money/:view" element={<Money />} />
          <Route path="money/:view/:id" element={<Money />} />
          <Route path="todo" element={<Todo />} />
          <Route path="settings" element={<Settings />} />
          <Route path="activity" element={<Activity />} />
          <Route path="documents/:id" element={<DocumentDetail />} />
          <Route path="matches/:id" element={<MatchRedirect />} />
          <Route path="inbox" element={<Navigate to="/todo" replace />} />
          <Route path="inbox/:id" element={<To path={(p) => `/todo#${p.id}`} />} />
          <Route path="transactions/:id" element={<To path={(p) => `/money/payments/${p.id}`} />} />
          <Route path="transactions" element={<Navigate to="/money/payments" replace />} />
          <Route path="documents" element={<Navigate to="/money/payments" replace />} />
          <Route path="ledger" element={<Navigate to="/money" replace />} />
          <Route path="accounts/:accountId" element={<Navigate to="/settings#accounts" replace />} />
          <Route path="sources" element={<Navigate to="/settings#accounts" replace />} />
          <Route path="chat" element={<Navigate to="/?ask=1" replace />} />
          <Route path="forecast/:id" element={<Navigate to="/#cash" replace />} />
          <Route path="*" element={<NotBuiltYet />} />
        </Route>
      </Routes>
    </CompanyProvider>
  );
}
