import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type Company } from "../api/client";
import { DEFAULT_COMPANY_ID } from "../config";

type CompanyState = { companyId: string; setCompanyId: (id: string) => void; companies: Company[] | null };
const CompanyContext = createContext<CompanyState>({ companyId: DEFAULT_COMPANY_ID, setCompanyId: () => {}, companies: null });
const KEY = "ordo.company";

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
    }
  };
  return <CompanyContext.Provider value={{ companyId, setCompanyId, companies }}>{children}</CompanyContext.Provider>;
}

export const useCompany = () => useContext(CompanyContext);

export function useCompanyInfo(): Company | null {
  const { companyId, companies } = useCompany();
  return companies?.find((c) => c.id === companyId) ?? null;
}

export function useToday(): string {
  return useCompanyInfo()?.as_of_date ?? new Date().toISOString().slice(0, 10);
}
