import { createContext, useContext, useState, type ReactNode } from "react";
import { DEFAULT_COMPANY_ID } from "../config";

const CompanyContext = createContext<{ companyId: string; setCompanyId: (id: string) => void }>({ companyId: DEFAULT_COMPANY_ID, setCompanyId: () => {} });

export function CompanyProvider({ children }: { children: ReactNode }) {
  const [companyId, setCompanyId] = useState(DEFAULT_COMPANY_ID);
  return <CompanyContext.Provider value={{ companyId, setCompanyId }}>{children}</CompanyContext.Provider>;
}

export const useCompany = () => useContext(CompanyContext);
