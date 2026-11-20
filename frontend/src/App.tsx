import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { CompanyProvider } from "./lib/company";
import { Activity } from "./pages/Activity";
import { Chat } from "./pages/Chat";
import { Dashboard } from "./pages/Dashboard";
import { DocumentDetail, Documents } from "./pages/Documents";
import { Inbox, InboxDetail } from "./pages/Inbox";
import { NotBuiltYet } from "./pages/NotBuiltYet";
import { Sources } from "./pages/Sources";

export function App() {
  return (
    <CompanyProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="inbox" element={<Inbox />} />
          <Route path="inbox/:id" element={<InboxDetail />} />
          <Route path="documents" element={<Documents />} />
          <Route path="documents/:id" element={<DocumentDetail />} />
          <Route path="sources" element={<Sources />} />
          <Route path="activity" element={<Activity />} />
          <Route path="chat" element={<Chat />} />
          <Route path="*" element={<NotBuiltYet />} />
        </Route>
      </Routes>
    </CompanyProvider>
  );
}
