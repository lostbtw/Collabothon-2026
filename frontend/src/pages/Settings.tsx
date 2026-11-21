// Settings: everything Ordo needs to know about the company, and what it may do.
// Company, alerts, people and rules come from the settings endpoints role 1 is adding; accounts and
// sources from the connectors. A section whose data the backend does not send yet says so.
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { api, exportUrl, type Person, type Rule, type Settings as SettingsData } from "../api/client";
import type { Account, Source } from "../api/types.gen";
import { PageHead, Skeleton, Toggle, Waiting } from "../components/ui";
import { ago, useNow } from "../lib/clock";
import { COST_TYPES } from "../lib/costTypes";
import { useCompany } from "../lib/company";
import { shortDate } from "../lib/dates";
import { formatMoney } from "../lib/money";
import { requestRefresh, useRefreshKey } from "../lib/refresh";
import { useApi } from "../lib/useApi";
import { PAY_LABEL, ROLE_LABEL, categoryLabel, initials, plainName } from "../lib/words";
import { parseAmount } from "./inbox/model";
import { Avatar } from "../components/ui";

const SECTIONS = [
  ["company", "Company"], ["accounts", "Accounts and cards"], ["invoices", "Invoices"], ["people", "People"],
  ["sorting", "Sorting costs"], ["autonomy", "What Ordo may do"], ["alerts", "Alerts"], ["data", "Your data"],
] as const;
const none = <T,>(p: Promise<T>): Promise<T | null> => p.catch(() => null);

export function Settings() {
  const { companyId } = useCompany();
  const refresh = useRefreshKey();
  const { hash } = useLocation();
  const [reload, setReload] = useState(0);
  const state = useApi(() => Promise.all([
    none(api.settings(companyId)), none(api.accounts(companyId)), none(api.sources(companyId)), none(api.people(companyId)), none(api.rules(companyId)),
  ]), [companyId, refresh, reload]);
  const [settings, accounts, sources, people, rules] = state.data ?? [null, null, null, null, null];
  const again = () => setReload((n) => n + 1);
  const active = useActiveSection(hash.replace("#", "") || "company", Boolean(state.data));
  return (
    <>
      <PageHead title="Settings" sub="Everything Ordo needs to know about your company, and what it may do." />
      <div className="hstack" style={{ alignItems: "flex-start", gap: 32, flexWrap: "nowrap" }}>
        <nav className="settings-menu" aria-label="Settings sections">
          {SECTIONS.map(([id, label]) => <a key={id} href={`#${id}`} className={`nav-item${active === id ? " active" : ""}`}>{label}</a>)}
        </nav>
        {state.loading && !state.data ? <div className="grow"><Skeleton rows={8} title /></div> : (
          <div className="stack grow" style={{ gap: 24 }}>
            <CompanySection settings={settings} onSaved={again} />
            <AccountsSection accounts={accounts?.items ?? []} sources={sources?.items ?? []} />
            <InvoicesSection sources={sources?.items ?? []} />
            <PeopleSection people={people?.items ?? null} onChanged={again} />
            <SortingSection rules={rules?.items ?? null} onChanged={again} />
            <AutonomySection />
            <AlertsSection settings={settings} onSaved={again} />
            <DataSection />
          </div>
        )}
      </div>
    </>
  );
}

/** The section the owner is reading: the last one whose top has scrolled past the upper third of the window. */
function useActiveSection(initial: string, ready: boolean): string {
  const [active, setActive] = useState(initial);
  useEffect(() => { setActive(initial); }, [initial]);
  useEffect(() => {
    if (!ready) return;
    const onScroll = () => {
      const line = window.innerHeight / 3;
      let current = SECTIONS[0][0] as string;
      for (const [id] of SECTIONS) {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top <= line) current = id;
      }
      // At the very bottom the last section is the one being read, even if it is short.
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) current = SECTIONS[SECTIONS.length - 1][0];
      setActive(current);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [ready]);
  return active;
}

function Section({ id, title, sub, children }: { id: string; title: string; sub: string; children: ReactNode }) {
  return (
    <section id={id} className="card stack" style={{ gap: 0 }}>
      <h2>{title}</h2>
      <span className="small t2" style={{ marginBottom: 8 }}>{sub}</span>
      {children}
    </section>
  );
}

function Setting({ title, note, children }: { title: string; note?: ReactNode; children?: ReactNode }) {
  return (
    <div className="setting">
      <div className="stack grow" style={{ gap: 0 }}>
        <span>{title}</span>
        {note && <span className="small t3">{note}</span>}
      </div>
      {children}
    </div>
  );
}

/** Saves one change and says so; the backend may not have the settings endpoint yet. */
function useSave(onSaved: () => void) {
  const { companyId } = useCompany();
  const [status, setStatus] = useState<string | null>(null);
  async function save(body: Parameters<typeof api.patchSettings>[1]) {
    setStatus("Saving…");
    try {
      const saved = await api.patchSettings(companyId, body);
      setStatus(saved ? "Saved" : "Not saved: the backend cannot store settings yet.");
      if (saved) onSaved();
    } catch (e) {
      setStatus(`Not saved: ${e instanceof Error ? e.message : String(e)}`);
    }
  }
  return { status, save };
}

function CompanySection({ settings, onSaved }: { settings: SettingsData | null; onSaved: () => void }) {
  const { status, save } = useSave(onSaved);
  const c = settings?.company;
  return (
    <Section id="company" title="Company" sub="Used on every calculation and when Ordo checks invoices.">
      {!c ? <Waiting what="company settings" /> : (
        <>
          <Setting title="Company name"><TextField value={c.name} onSave={(name) => save({ company: { name } })} /></Setting>
          <Setting title="Tax number (NIP)" note="Ordo checks that it is printed on every purchase invoice."><TextField value={c.tax_id ?? ""} onSave={(tax_id) => save({ company: { tax_id } })} /></Setting>
          <Setting title="VAT" note="How often you pay VAT.">
            <div className="tabs">
              {(["monthly", "quarterly"] as const).map((p) => <button key={p} type="button" className={c.vat_period === p ? "on" : undefined} onClick={() => save({ company: { vat_period: p } })}>{p === "monthly" ? "Monthly" : "Quarterly"}</button>)}
            </div>
          </Setting>
          <Setting title="Main currency" note="Foreign amounts are converted with the NBP rate."><span className="field">{c.base_currency}</span></Setting>
          <Setting title="Accountant's e-mail" note="Where Ordo sends a month's documents when you close it."><TextField value={c.accountant_email ?? ""} onSave={(accountant_email) => save({ company: { accountant_email } })} /></Setting>
          {status && <span className="small t3" role="status">{status}</span>}
        </>
      )}
    </Section>
  );
}

function TextField({ value, onSave }: { value: string; onSave: (v: string) => void }) {
  const [text, setText] = useState(value);
  return <input type="text" value={text} onChange={(e) => setText(e.target.value)} onBlur={() => text.trim() !== value && onSave(text.trim())} style={{ width: 320, borderRadius: "var(--radius-md)" }} />;
}

function AccountsSection({ accounts, sources }: { accounts: Account[]; sources: Source[] }) {
  const now = useNow(30_000);
  const [adding, setAdding] = useState(false);
  const [added, setAdded] = useState<string[]>([]);
  const banks = sources.filter((s) => s.connector === "bank_psd2");
  const sourceOf = (a: Account) => sources.find((s) => s.id === a.source_id) ?? banks.find((s) => String(s.config_public?.iban_masked ?? "").slice(-4) === (a.iban_masked ?? "").slice(-4)) ?? null;
  function connect(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const name = String(new FormData(e.currentTarget).get("name") ?? "").trim();
    if (name) setAdded([...added, name]);
    setAdding(false);
  }
  return (
    <Section id="accounts" title="Bank accounts and cards" sub="Ordo only reads these. Nothing here can move money.">
      {accounts.length === 0 && <span className="small t2">No accounts connected yet.</span>}
      {accounts.map((a) => {
        const s = sourceOf(a);
        const iban = a.iban_masked ?? (s?.config_public?.iban_masked as string | undefined) ?? null;
        const ok = !s || s.status === "connected" || s.status === "syncing";
        return (
          <Setting key={a.id} title={a.name}
            note={[s?.is_sandbox === false ? "Bank" : "Sandbox Bank", iban && `${iban.slice(0, 4)} ${iban.slice(-4)}`, a.card_last4?.length ? `card ending ${a.card_last4.join(", ")}` : null,
              s?.items_total ? `${s.items_total.toLocaleString("en")} payments read` : null, a.include_in_liquidity ? null : "only company costs on it are counted"].filter(Boolean).join(" · ")}>
            <SourceStatus source={s} ok={ok} now={now} />
            {s && <SyncNow source={s} />}
            {!a.include_in_liquidity && <span className="hstack small t2" style={{ gap: 8 }}>Count as company cash <Toggle on={false} label="Count as company cash" /></span>}
          </Setting>
        );
      })}
      {added.map((name) => <Setting key={name} title={name} note="Sandbox Bank · added in this tab"><span className="simulated">SIMULATED · connected</span></Setting>)}
      <div className="setting">
        {adding ? (
          <form className="hstack" onSubmit={connect}>
            <label className="pill-select"><select aria-label="Bank" defaultValue="sandbox"><option value="sandbox">Sandbox Bank</option></select></label>
            <input type="text" name="name" placeholder="Account name" aria-label="Account name" autoFocus />
            <button type="submit" className="primary">Connect (simulated)</button>
            <button type="button" className="quiet" onClick={() => setAdding(false)}>Cancel</button>
          </form>
        ) : <button type="button" onClick={() => setAdding(true)}>Connect a bank account (simulated)</button>}
        <span className="small t3">Only test banks in this demo.</span>
      </div>
    </Section>
  );
}

/** Green or amber dot, "Synced 2 min ago" (ticking), and the last error in words when there is one. */
function SourceStatus({ source, ok, now }: { source: Source | null; ok: boolean; now: number | null }) {
  return (
    <span className="hstack small t3" style={{ gap: 6 }} title={source?.last_error?.message ?? undefined}>
      <span className="dot" style={{ background: ok ? "var(--good)" : "var(--warn)" }} />
      {source?.last_synced_at && now ? `Synced ${ago(source.last_synced_at, now)}` : ok ? "Connected" : "Needs attention"}
    </span>
  );
}

/** Asks the connector to read the source now; the status above updates live when the run finishes. */
function SyncNow({ source }: { source: Source }) {
  const [state, setState] = useState<"idle" | "busy" | "asked" | "failed">("idle");
  async function sync() {
    setState("busy");
    try {
      await api.syncNow(source.id);
      setState("asked");
      setTimeout(() => { requestRefresh(); setState("idle"); }, 3000);
    } catch {
      setState("failed");
    }
  }
  return <button type="button" className="quiet" disabled={state === "busy" || state === "asked"} onClick={sync}>
    {state === "busy" ? "Asking…" : state === "asked" ? "Reading…" : state === "failed" ? "Try again" : "Sync now"}
  </button>;
}

function InvoicesSection({ sources }: { sources: Source[] }) {
  const mail = sources.find((s) => s.connector === "imap_mailbox") ?? null;
  const mailbox = mail?.config_public?.mailbox as string | undefined;
  const now = useNow(30_000);
  const rates = sources.find((s) => s.connector === "fx_rates");
  const [copied, setCopied] = useState(false);
  return (
    <Section id="invoices" title="Invoices and receipts" sub="Nobody uploads anything by hand unless they want to.">
      <Setting title="Forwarding address" note="Staff forward invoices and receipts here. Ordo reads them on its own.">
        {mailbox ? (
          <>
            <span className="field">{mailbox}</span>
            <button type="button" className="quiet" onClick={() => { void navigator.clipboard?.writeText(mailbox); setCopied(true); }}>{copied ? "Copied" : "Copy"}</button>
          </>
        ) : <span className="small t3">No mailbox connected</span>}
      </Setting>
      {mail && (
        <Setting title="Mailbox" note={mail.items_total ? `${mail.items_total.toLocaleString("en")} e-mails and files read` : "Nothing read yet"}>
          <SourceStatus source={mail} ok={mail.status === "connected" || mail.status === "syncing"} now={now} />
          <SyncNow source={mail} />
        </Setting>
      )}
      <Setting title="Accept e-mails from" note="Anything from other senders waits for you in To-do."><span className="small t2">People below and known suppliers</span></Setting>
      <Setting title="Exchange rates" note="For invoices in other currencies."><span className="small t2">{rates ? `${rates.display_name}, daily` : "National Bank of Poland, daily"}</span></Setting>
    </Section>
  );
}

function PeopleSection({ people, onChanged }: { people: Person[] | null; onChanged: () => void }) {
  const { companyId } = useCompany();
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const text = (k: string) => String(f.get(k) ?? "").trim();
    try {
      const saved = await api.addPerson(companyId, {
        name: text("name"), email: text("email"), role: text("role"), pay_type: text("role") === "contractor" ? "invoice" : "salary",
        card_last4: text("card") ? [text("card")] : [], statement_names: text("statement") ? [text("statement").toUpperCase()] : [], tax_id: null, iban: null,
      });
      if (!saved) return setError("Not saved: the backend cannot store people yet.");
      setAdding(false);
      setError(null);
      onChanged();
    } catch (err) {
      setError(`Not saved: ${err instanceof Error ? err.message : String(err)}`);
    }
  }
  return (
    <Section id="people" title="People" sub="Ordo uses this to tell who paid a receipt and what each person costs.">
      {!people ? <Waiting what="the people list" /> : (
        <>
          <div className="trow head" style={{ paddingLeft: 0, paddingRight: 0 }}>
            <span className="cell grow">Person</span><span className="cell" style={{ width: 230 }}>Sends receipts from</span><span className="cell" style={{ width: 110 }}>Cards</span><span className="cell" style={{ width: 170 }}>Name on bank statements</span>
          </div>
          {people.map((p) => (
            <div key={p.id} className="trow" style={{ paddingLeft: 0, paddingRight: 0 }}>
              <span className="cell grow" style={{ gap: 12 }}>
                <Avatar text={initials(p.name)} />
                <span className="stack" style={{ gap: 0 }}><span>{plainName(p.name)}</span><span className="caption t3">{[ROLE_LABEL[p.role] ?? p.role, p.pay_type && PAY_LABEL[p.pay_type]?.toLowerCase()].filter(Boolean).join(" · ")}</span></span>
              </span>
              <span className="cell small t2" style={{ width: 230 }}>{p.email}</span>
              <span className="cell small t2" style={{ width: 110 }}>{p.card_last4.length ? p.card_last4.map((c) => `ending ${c}`).join(", ") : "—"}</span>
              <span className="cell small t2" style={{ width: 170 }}>{p.statement_names.join(", ") || "—"}</span>
            </div>
          ))}
          <div className="setting">
            {adding ? (
              <form className="hstack" onSubmit={add}>
                <input type="text" name="name" placeholder="Name" aria-label="Name" required autoFocus />
                <input type="text" name="email" placeholder="E-mail" aria-label="E-mail" required />
                <label className="pill-select"><select name="role" aria-label="Role" defaultValue="employee"><option value="employee">Employee</option><option value="contractor">Contractor</option></select></label>
                <input type="text" name="card" placeholder="Card ending" aria-label="Card ending" style={{ width: 120 }} />
                <input type="text" name="statement" placeholder="Name on statements" aria-label="Name on bank statements" />
                <button type="submit" className="primary">Add</button>
                <button type="button" className="quiet" onClick={() => setAdding(false)}>Cancel</button>
              </form>
            ) : <button type="button" onClick={() => setAdding(true)}>Add a person</button>}
          </div>
          {error && <span className="small bad" role="alert">{error}</span>}
        </>
      )}
    </Section>
  );
}

function SortingSection({ rules, onChanged }: { rules: Rule[] | null; onChanged: () => void }) {
  const { companyId } = useCompany();
  const [error, setError] = useState<string | null>(null);
  async function remove(id: string) {
    try {
      const done = await api.deleteRule(id, companyId);
      if (done === null) return setError("Not deleted: the backend cannot delete rules yet.");
      setError(null);
      onChanged();
    } catch (e) {
      setError(`Not deleted: ${e instanceof Error ? e.message : String(e)}`);
    }
  }
  return (
    <Section id="sorting" title="How Ordo sorts costs" sub="In this order: what you corrected before, then simple word rules, then the AI picks one of your cost types. If nothing fits, it says “Not explained yet”.">
      <Setting title="Cost types">
        <div className="hstack" style={{ justifyContent: "flex-end", maxWidth: 560 }}>
          {COST_TYPES.map((t) => <span key={t.key} className="chip neutral hstack" style={{ gap: 6 }}><span className="dot" style={{ background: t.color }} />{t.label}</span>)}
          <span className="chip neutral hstack" style={{ gap: 6 }}><span className="dot" style={{ background: "var(--cat-none)" }} />Personal</span>
        </div>
      </Setting>
      <span className="small medium" style={{ padding: "16px 0 4px", borderTop: "1px solid var(--border)" }}>Rules Ordo learned from you</span>
      {!rules ? <Waiting what="the learned rules" /> : rules.length === 0 ? <span className="small t2">None yet. Each time you change a type, Ordo learns a rule.</span> : rules.map((r) => (
        <div key={r.id} className="setting">
          <span className="small grow"><code>{r.raw}</code> → <span className="medium">{plainName(r.counterparty_name)}</span>{r.category ? ` · ${categoryLabel(r.category)}` : ""}</span>
          {r.learned_at && <span className="small t3">{shortDate(r.learned_at)}</span>}
          <button type="button" className="quiet" onClick={() => remove(r.id)}>Delete</button>
        </div>
      ))}
      {error && <span className="small bad" role="alert">{error}</span>}
    </Section>
  );
}

function AutonomySection() {
  return (
    <Section id="autonomy" title="What Ordo may do on its own" sub="Anything Ordo does alone can be undone. Money never moves without you. Set by the team for this demo.">
      <Setting title="Sort costs into types" note="You can always change a type. Ordo remembers your change."><Toggle on label="Sort costs into types" /></Setting>
      <Setting title="Confirm a payment and its invoice" note="Only when it is at least 90% sure and the payment repeats every month."><Toggle on label="Confirm a payment and its invoice" /></Setting>
      <Setting title="Prepare payments, reminders and applications" note="They wait in To-do until you approve them."><Toggle on label="Prepare payments, reminders and applications" /></Setting>
      <Setting title="Pay, transfer or apply without asking" note="Not possible. Ordo always asks first."><span className="chip neutral">Always asks</span></Setting>
      <Setting title="Mode" note="This version only talks to the test bank."><span className="chip info">Simulated</span></Setting>
    </Section>
  );
}

function AlertsSection({ settings, onSaved }: { settings: SettingsData | null; onSaved: () => void }) {
  const { status, save } = useSave(onSaved);
  const a = settings?.alerts;
  const currency = settings?.company.base_currency ?? "PLN";
  const [buffer, setBuffer] = useState(a?.safety_buffer ? formatMoney(a.safety_buffer, { decimals: false }).replace(` ${a.safety_buffer.currency}`, "") : "");
  const [late, setLate] = useState(String(a?.late_client_days ?? ""));
  const [bad, setBad] = useState<string | null>(null);
  function saveBuffer() {
    const amount = parseAmount(buffer);
    if (!amount) return setBad("Enter an amount such as 10,000.");
    setBad(null);
    if (amount !== a?.safety_buffer?.amount) void save({ alerts: { safety_buffer: { amount, currency } } });
  }
  function saveLate() {
    const days = Number(late);
    if (!Number.isInteger(days) || days < 1) return setBad("Enter a whole number of days, such as 7.");
    setBad(null);
    if (days !== a?.late_client_days) void save({ alerts: { late_client_days: days } });
  }
  return (
    <Section id="alerts" title="Alerts" sub="When Ordo should tell you something, even if you don't open it.">
      {!a ? <Waiting what="alert settings" /> : (
        <>
          <Setting title="Warn me when cash may drop below" note="Ordo checks every day, 45 days ahead.">
            <span className="hstack small t2" style={{ gap: 8 }}><input type="text" value={buffer} onChange={(e) => setBuffer(e.target.value)} onBlur={saveBuffer} aria-label="Safety buffer" style={{ width: 120 }} />{currency}</span>
          </Setting>
          <Setting title="Tell me when a client is late by more than">
            <span className="hstack small t2" style={{ gap: 8 }}><input type="text" value={late} onChange={(e) => setLate(e.target.value)} onBlur={saveLate} aria-label="Days late" style={{ width: 70 }} />days</span>
          </Setting>
          <Setting title="Weekly summary by e-mail" note="Every Monday at 8:00: cash, costs and what needs you. Simulated: no e-mail leaves the app.">
            <Toggle on={a.weekly_summary} label="Weekly summary by e-mail" onChange={(on) => save({ alerts: { weekly_summary: on } })} />
          </Setting>
          {(bad || status) && <span className={`small ${bad ? "bad" : "t3"}`} role="status">{bad ?? status}</span>}
        </>
      )}
    </Section>
  );
}

function DataSection() {
  const { companyId } = useCompany();
  const url = exportUrl(companyId);
  return (
    <Section id="data" title="Your data" sub="Everything Ordo knows, and everything it did.">
      <Setting title="Export everything" note="All payments, invoices and books as CSV files.">
        {url ? <a className="button" href={url}>Export (CSV)</a> : <span className="small t3">Live data only</span>}
      </Setting>
      <Setting title="What Ordo did on its own" note="Every step it took without asking. Anything there can be undone.">
        <Link to="/activity" className="button">Open the log</Link>
      </Setting>
    </Section>
  );
}
