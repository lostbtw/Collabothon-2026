import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { PageState } from "../components/PageState";
import { useCompany } from "../lib/company";
import { formatMoney } from "../lib/money";
import { useApi } from "../lib/useApi";

export function Documents() {
  const { companyId } = useCompany();
  const state = useApi(() => api.documents(companyId), [companyId]);
  return (
    <>
      <h1>Documents</h1>
      <PageState state={state} empty={(d) => d.items.length === 0}>
        {(page) => (
          <div className="card table-card">
            <table>
              <thead><tr><th>Seller</th><th>Type</th><th>Date</th><th>Total</th><th>Status</th></tr></thead>
              <tbody>
                {page.items.map((d) => (
                  <tr key={d.id}>
                    <td><Link to={`/documents/${d.id}`}>{d.seller.name}</Link></td>
                    <td>{d.doc_type.replace("_", " ")}</td>
                    <td>{d.issue_date ?? "—"}</td>
                    <td>{formatMoney(d.totals.gross)}</td>
                    <td>{d.status.replace("_", " ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </PageState>
    </>
  );
}

export function DocumentDetail() {
  const { id = "" } = useParams();
  const state = useApi(() => api.document(id), [id]);
  return (
    <PageState state={state}>
      {({ document: d, matches }) => (
        <div className="stack">
          <h1>{d.seller.name}</h1>
          <div className="card">
            <dl className="fields">
              <dt>Number</dt><dd>{d.number ?? "—"}</dd>
              <dt>Date</dt><dd>{d.issue_date ?? "—"}</dd>
              <dt>Total</dt><dd>{formatMoney(d.totals.gross)}</dd>
              <dt>VAT</dt><dd>{formatMoney(d.totals.vat)}</dd>
              <dt>Buyer tax number</dt><dd>{d.buyer.tax_id ?? "Not found on the document"}</dd>
              <dt>Read with confidence</dt><dd>{Math.round(d.extraction.confidence * 100)}%</dd>
              <dt>Flags</dt><dd>{d.flags.length ? d.flags.map((f) => f.replaceAll("_", " ")).join(", ") : "none"}</dd>
            </dl>
          </div>
          {matches.map((m) => (
            <div key={m.id} className="card">
              <h2>Who paid: {m.paid_by.replaceAll("_", " ")}</h2>
              <ul className="plain">{m.reasons.map((r) => <li key={r.rule}>{r.detail}</li>)}</ul>
            </div>
          ))}
          <p><Link to="/documents">Back to documents</Link></p>
        </div>
      )}
    </PageState>
  );
}
