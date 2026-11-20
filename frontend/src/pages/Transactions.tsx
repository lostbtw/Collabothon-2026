import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Counterparty, Transaction } from "../api/types.gen";
import { PageState } from "../components/PageState";
import { useCompany } from "../lib/company";
import { shortDate } from "../lib/dates";
import { formatMoney, isNegative } from "../lib/money";
import { useApi } from "../lib/useApi";

const DOCUMENT: Record<Transaction["match_status"], { label: string; tone: string }> = {
  matched: { label: "Matched", tone: "positive" },
  suggested: { label: "Suggested", tone: "warning" },
  unmatched: { label: "Not matched", tone: "neutral" },
  missing_document: { label: "Missing", tone: "danger" },
  no_document_needed: { label: "Not needed", tone: "neutral" },
};
const words = (s: string) => s.replaceAll("_", " ");

/** Bank lines. `/accounts/:accountId` shows one account; `/transactions/:id` marks one line. */
export function Transactions() {
  const { companyId } = useCompany();
  const { accountId, id } = useParams();
  const state = useApi(() => Promise.all([api.transactions(companyId, accountId), api.counterparties(companyId).catch(() => ({ items: [] }))]), [companyId, accountId]);
  return (
    <>
      <div className="hstack"><h1>Transactions</h1>{accountId && <Link to="/transactions" className="chip neutral">One account · show all</Link>}</div>
      <PageState state={state} empty={([t]) => t.items.length === 0}>
        {([page, parties]) => <TransactionsView items={page.items} parties={parties.items} marked={id} />}
      </PageState>
    </>
  );
}

export function TransactionsView({ items, parties, marked }: { items: Transaction[]; parties: Counterparty[]; marked?: string }) {
  const name = (t: Transaction) => parties.find((p) => p.id === t.counterparty_id)?.name ?? t.counterparty_name_raw ?? t.description;
  return (
    <div className="card table-card">
      <table>
        <thead><tr><th>Date</th><th>To / From</th><th>Category</th><th>Document</th><th className="right">Amount</th></tr></thead>
        <tbody>
          {items.map((t) => (
            <tr key={t.id} className={t.id === marked ? "marked" : undefined} title={t.description}>
              <td className="tertiary">{shortDate(t.booking_date)}</td>
              <td>{name(t)}{(t.data_quality?.length ?? 0) > 0 && <span className="chip neutral" style={{ marginLeft: 8 }} title={t.fx?.source ?? undefined}>converted</span>}</td>
              <td className="tertiary">{t.category ? words(t.category) : "—"}</td>
              <td><span className={`chip ${DOCUMENT[t.match_status].tone}`}>{DOCUMENT[t.match_status].label}</span></td>
              <td className={`right${isNegative(t.amount_base) ? "" : " positive"}`}>
                {formatMoney(t.amount_base)}
                {t.original_amount && t.original_amount.currency !== t.amount_base.currency && <div className="caption muted">{formatMoney(t.original_amount)}</div>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
