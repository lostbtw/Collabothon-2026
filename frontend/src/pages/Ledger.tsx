import { useState } from "react";
import { api, type LedgerSummary } from "../api/client";
import type { LedgerEntry } from "../api/types.gen";
import { Evidence } from "../components/More";
import { PageState } from "../components/PageState";
import { API_BASE, API_MODE } from "../config";
import { useCompany } from "../lib/company";
import { shortDate } from "../lib/dates";
import { formatMoney, isNegative } from "../lib/money";
import { useRefreshKey } from "../lib/refresh";
import { useApi } from "../lib/useApi";

const STATUS: Record<LedgerEntry["status"], string> = { proposed: "warning", approved: "positive", void: "neutral" };
const PAID_BY: Record<NonNullable<LedgerEntry["paid_by"]>, string> = { company_account: "Company", owner_private: "Owner, privately", employee_private: "Employee, privately", unknown: "Not known", not_applicable: "—" };
const words = (s: string) => s.replaceAll("_", " ");
const title = (s: string) => words(s).replace(/^./, (c) => c.toUpperCase());

export function Ledger() {
  const { companyId } = useCompany();
  const refresh = useRefreshKey();
  const state = useApi(() => Promise.all([api.ledger(companyId), api.ledgerSummary(companyId).catch(() => null)]), [companyId, refresh]);
  return (
    <>
      <div className="hstack">
        <h1>Ledger</h1>
        <span className="grow" />
        {API_MODE === "live" && <a className="button outline" href={`${API_BASE}/ledger/export?company_id=${encodeURIComponent(companyId)}`}>Export CSV</a>}
      </div>
      <PageState state={state} empty={([l]) => l.items.length === 0}>
        {([page, summary]) => <LedgerView entries={page.items} summary={summary} />}
      </PageState>
    </>
  );
}

export function LedgerView({ entries, summary }: { entries: LedgerEntry[]; summary: LedgerSummary | null }) {
  const k = summary?.kpis;
  return (
    <>
      {k && (
        <div className="row">
          <Stat label="Owed to the team" value={formatMoney(k.reimbursements_owed, { decimals: false })} />
          <Stat label="Tax due in 30 days" value={formatMoney(k.tax_due_next_30d, { decimals: false })} />
          <Stat label="VAT lost this year" value={formatMoney(k.vat_lost_ytd)} />
          <Stat label="Documents missing" value={String(k.documents_missing)} />
        </div>
      )}
      <div className="card table-card">
        <table>
          <thead><tr><th>Date</th><th>Entry</th><th>Paid by</th><th>Status</th><th className="right">VAT</th><th className="right">Amount</th><th /></tr></thead>
          <tbody>{entries.map((e) => <Entry key={e.id} e={e} />)}</tbody>
        </table>
      </div>
    </>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return <div className="card stack" style={{ gap: 4 }}><div className="tertiary">{label}</div><div className="display">{value}</div></div>;
}

function Entry({ e }: { e: LedgerEntry }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr className={open ? "open" : undefined}>
        <td className="tertiary">{shortDate(e.date)}</td>
        <td>{title(e.category)}<span className="muted"> · {words(e.type)}</span></td>
        <td className="tertiary">{PAID_BY[e.paid_by ?? "not_applicable"]}</td>
        <td><span className={`chip ${STATUS[e.status]}`}>{title(e.status)}</span></td>
        <td className="right tertiary">{e.vat ? `${formatMoney(e.vat.amount)}${e.vat.deductible ? "" : " · lost"}` : "—"}</td>
        <td className={`right${isNegative(e.amount_base) ? "" : " positive"}`}>{formatMoney(e.amount_base)}</td>
        <td className="right"><button type="button" className="outline" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Hide" : "Why"}</button></td>
      </tr>
      {open && (
        <tr className="why">
          <td />
          <td colSpan={6}>
            <div className="stack" style={{ gap: 8 }}>
              <p>{e.explanation}</p>
              {e.vat?.reason && <p className="small tertiary">VAT: {e.vat.reason}</p>}
              {e.evidence && e.evidence.length > 0 && <Evidence links={e.evidence} />}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
