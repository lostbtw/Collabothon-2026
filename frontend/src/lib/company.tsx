import { createContext, useContext, useState, type ReactNode } from "react";
import { DEFAULT_COMPANY_ID } from "../config";

const CompanyContext = createContext<{ companyId: string; setCompanyId: (id: string) => void }>({ companyId: DEFAULT_COMPANY_ID, setCompanyId: () => {} });
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
  const setCompanyId = (id: string) => {
    setId(id);
    try {
      window.sessionStorage.setItem(KEY, id);
    } catch {
      // No sessionStorage: the choice lasts until the next reload.
    }
  };
  return <CompanyContext.Provider value={{ companyId, setCompanyId }}>{children}</CompanyContext.Provider>;
}

export const useCompany = () => useContext(CompanyContext);
