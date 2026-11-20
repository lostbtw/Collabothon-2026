import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type Company } from "../api/client";
import { DEFAULT_COMPANY_ID } from "../config";

type CompanyState = { companyId: string; setCompanyId: (id: string) => void; companies: Company[] | null };
const CompanyContext = createContext<CompanyState>({ companyId: DEFAULT_COMPANY_ID, setCompanyId: () => {}, companies: null });
const KEY = "ordo.company";

/** The selected company, remembered for the browser tab so a reload stays on it. */
function remembered(): string {
  try {
    return window.sessionStorage.getItem(KEY) ?? DEFAULT_COMPANY_ID;
  } catch {
    return DEFAULT_COMPANY_ID;
  }
}

export function CompanyProvider({ children }: { children: ReactNode }) {
  const [companyId, setId] = useState(remembered);
  const [companies, setCompanies] = useState<Company[] | null>(null);
  useEffect(() => { api.companies().then((c) => setCompanies(c.items), () => setCompanies([])); }, []);
  const setCompanyId = (id: string) => {
    setId(id);
    try {
      window.sessionStorage.setItem(KEY, id);
    } catch {
      // No sessionStorage: the choice lasts until the next reload.
    }
  };
  return <CompanyContext.Provider value={{ companyId, setCompanyId, companies }}>{children}</CompanyContext.Provider>;
}

export const useCompany = () => useContext(CompanyContext);

/** The selected company's record, once loaded. */
export function useCompanyInfo(): Company | null {
  const { companyId, companies } = useCompany();
  return companies?.find((c) => c.id === companyId) ?? null;
}

/** "Today" for the selected company: the day its data is seen on (the demo day), else the laptop's date. */
export function useToday(): string {
  return useCompanyInfo()?.as_of_date ?? new Date().toISOString().slice(0, 10);
}
