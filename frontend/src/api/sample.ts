// Sample-mode data the fixtures do not cover, all invented SAMPLE data; mock mode only, live mode asks the backend.
import type {
  BalanceHistory, ChatSession, ChatSessionDetail, ClientsResponse, PeopleCosts, Person, Rule, Settings, SubscriptionsResponse,
} from "./client";
import type { Approval, Counterparty, Money, OrdoDocument, Recommendation, Transaction } from "./types.gen";

const pln = (amount: string): Money => ({ amount, currency: "PLN" });
const addDays = (date: string, n: number): string =>
  new Date(Date.UTC(Number(date.slice(0, 4)), Number(date.slice(5, 7)) - 1, Number(date.slice(8, 10)) + n)).toISOString().slice(0, 10);

// What GET /ledger/summary?group_by=category&from&to returns, by month.
type Row = { key: string; amount_base: Money; change_pct: null; entries: number };
const rows = (list: [string, string, number][]): Row[] => list.map(([key, amount, entries]) => ({ key, amount_base: pln(amount), change_pct: null, entries }));

export const SUMMARY_BY_MONTH: Record<string, Row[]> = {
  "2026-11": rows([
    ["revenue_services", "4920.00", 1], ["contractors", "-10500.00", 1], ["rent_office", "-2460.00", 1], ["taxes", "-7050.00", 1],
    ["software_subscriptions", "-247.22", 2], ["equipment", "-1299.00", 1], ["travel", "-152.76", 1], ["meals_representation", "-238.68", 1], ["other", "-1840.00", 1],
  ]),
  "2026-10": rows([
    ["revenue_services", "131800.00", 4], ["salaries", "-15600.00", 3], ["contractors", "-42400.00", 4], ["social_security", "-9200.00", 1],
    ["rent_office", "-2460.00", 1], ["software_subscriptions", "-1148.00", 6], ["cloud_hosting", "-12952.00", 2], ["taxes", "-21600.00", 2],
    ["professional_services", "-1240.00", 1], ["travel", "-3100.00", 4], ["meals_representation", "-2250.00", 5], ["equipment", "-4850.00", 1],
    ["other", "-7800.00", 24], ["reimbursements", "-5169.00", 10],
  ]),
  "2026-09": rows([
    ["revenue_services", "117700.00", 4], ["salaries", "-15300.00", 3], ["contractors", "-42400.00", 4], ["social_security", "-9200.00", 1],
    ["rent_office", "-2460.00", 1], ["software_subscriptions", "-1050.00", 6], ["cloud_hosting", "-12350.00", 2], ["taxes", "-21000.00", 2],
    ["professional_services", "-1240.00", 1], ["travel", "-2600.00", 3], ["meals_representation", "-1600.00", 4], ["other", "-10600.00", 31],
  ]),
};
export const SUMMARY_KPIS = { reimbursements_owed: pln("5169.00"), vat_lost_ytd: pln("242.90"), documents_missing: 24, tax_due_next_30d: pln("25200.00") };

// Cash in the bank over the last three months (GET /balance/history).
const HISTORY_START = "2026-08-21";
const HISTORY: [number, string][] = [
  [0, "93300.00"], [10, "33300.00"], [13, "29600.00"], [18, "106400.00"], [25, "98900.00"], [30, "77900.00"], [35, "64300.00"], [37, "105200.00"],
  [40, "31200.00"], [43, "27500.00"], [47, "108600.00"], [54, "100600.00"], [55, "114400.00"], [60, "92400.00"], [65, "79500.00"], [67, "116400.00"],
  [71, "38400.00"], [81, "60400.00"], [91, "38400.00"],
];
export const BALANCE_HISTORY: BalanceHistory = { currency: "PLN", points: HISTORY.map(([d, balance]) => ({ date: addDays(HISTORY_START, d), balance })) };

// Counterparties the extra payments need.
const cp = (id: string, name: string, kind: Counterparty["kind"], default_category: string, extra: Partial<Counterparty> = {}): Counterparty =>
  ({ id, company_id: "co_borsuk", name, kind, default_category, ...extra });
export const SAMPLE_COUNTERPARTIES: Counterparty[] = [
  cp("cp_taxoffice", "Tax office Łódź-Polesie (SAMPLE)", "tax_authority", "taxes"),
  cp("cp_zus", "Social security office (SAMPLE)", "social_security", "social_security"),
  cp("cp_sklepik", "Sklepik.pl (SAMPLE)", "supplier", "other"),
  cp("cp_bistro", "Bistro Piotrkowska 90 (SAMPLE)", "supplier", "meals_representation"),
  cp("cp_rail", "RailExpress (SAMPLE)", "supplier", "travel"),
  cp("cp_cowork", "Coworking space (SAMPLE)", "supplier", "rent_office", { is_recurring: true }),
  cp("cp_kadrownia", "Kadrownia sp. z o.o. (SAMPLE)", "customer", "revenue_services", { typical_payment_delay_days: 2 }),
  cp("cp_meblostyl", "Meblostyl (SAMPLE)", "customer", "revenue_services", { typical_payment_delay_days: 0 }),
  cp("cp_piekarnia", "Piekarnia Złoty Kłos (SAMPLE)", "customer", "revenue_services", { typical_payment_delay_days: 1 }),
  cp("cp_lakeshore", "Lakeshore Robotics Inc. (SAMPLE)", "customer", "revenue_services"),
  cp("cp_lis", "Piotr Lis (SAMPLE)", "employee", "contractors", { person_id: "per_piotr" }),
  cp("cp_mazur", "Karolina Mazur (SAMPLE)", "employee", "contractors", { person_id: "per_karolina" }),
  cp("cp_wrona", "Anna Wrona (SAMPLE)", "employee", "contractors", { person_id: "per_anna" }),
  cp("cp_dudek", "Michał Dudek (SAMPLE)", "employee", "contractors", { person_id: "per_michal" }),
  cp("cp_kowalski", "Jan Kowalski (SAMPLE)", "employee", "salaries", { person_id: "per_jan" }),
  cp("cp_zielinska", "Marta Zielińska (SAMPLE)", "employee", "salaries", { person_id: "per_marta" }),
  cp("cp_borsuk", "Tomasz Borsuk (SAMPLE)", "owner", "salaries", { person_id: "per_tomasz" }),
  cp("cp_chmura", "Chmura Polska (SAMPLE)", "supplier", "cloud_hosting", { is_recurring: true }),
  cp("cp_serwer", "Serwerownia Łódź (SAMPLE)", "supplier", "cloud_hosting", { is_recurring: true }),
  cp("cp_logbear", "LogBear (SAMPLE)", "supplier", "software_subscriptions", { is_recurring: true }),
  cp("cp_rechenwerk", "Rechenwerk (SAMPLE)", "supplier", "software_subscriptions", { is_recurring: true }),
  cp("cp_mailbox", "Mailbox Pro (SAMPLE)", "supplier", "software_subscriptions", { is_recurring: true }),
  cp("cp_figment", "Figment Design (SAMPLE)", "supplier", "software_subscriptions", { is_recurring: true }),
  cp("cp_abakus", "Abakus accounting office (SAMPLE)", "supplier", "professional_services", { is_recurring: true }),
  cp("cp_lot", "SkyLink Airlines (SAMPLE)", "supplier", "travel"),
  cp("cp_trattoria", "Trattoria Manufaktura (SAMPLE)", "supplier", "meals_representation"),
  cp("cp_allegro", "Marketplace order (SAMPLE)", "supplier", "other"),
  cp("cp_koszyk", "Koszyk 24 (SAMPLE)", "supplier", "other"),
  cp("cp_taxigo", "Taxigo (SAMPLE)", "supplier", "other"),
  cp("cp_parkuj", "Parkuj.pl (SAMPLE)", "supplier", "other"),
];

// Extra bank and card lines, in the shape the bank connector delivers.
type TxnExtra = Partial<Transaction>;
const SOURCE: Record<string, string> = { acc_pln: "src_bank_pln", acc_eur: "src_bank_eur", acc_owner: "src_bank_owner" };
const txn = (id: string, account_id: string, booking_date: string, amount: string, raw: string, counterparty_id: string | null, category: Transaction["category"], match_status: Transaction["match_status"], extra: TxnExtra = {}): Transaction => ({
  id, account_id, source_id: SOURCE[account_id], raw_item_id: `raw_${id}`, external_id: `ext_${id}`, booking_date, amount: pln(amount), amount_base: pln(amount),
  counterparty_name_raw: raw, counterparty_id, description: raw, status: "booked", category, match_status,
  transaction_type: amount.startsWith("-") ? "transfer_out" : "transfer_in", ...extra,
});
const card = (last4: string): TxnExtra => ({ transaction_type: "card_payment", card_last4: last4 });

export const SAMPLE_TRANSACTIONS: Transaction[] = [
  // November, up to the demo day
  txn("txn_s_tax1120", "acc_pln", "2026-11-20", "-7050.00", "URZAD SKARBOWY LODZ-POLESIE PIT-4R CIT-8", "cp_taxoffice", "taxes", "no_document_needed", { transaction_type: "tax" }),
  txn("txn_s_sklepik", "acc_pln", "2026-11-18", "-1840.00", "SKLEPIK.PL WARSZAWA", "cp_sklepik", "other", "missing_document", card("4417")),
  txn("txn_s_bistro", "acc_pln", "2026-11-18", "-238.68", "BISTRO PIOTRKOWSKA 90 LODZ", "cp_bistro", "meals_representation", "missing_document", card("4417")),
  txn("txn_s_rail", "acc_owner", "2026-11-17", "-152.76", "RAILEXPRESS BILETY", "cp_rail", "travel", "matched", card("9021")),
  txn("txn_s_cowork", "acc_pln", "2026-11-14", "-2460.00", "BIURO NA PIOTRKOWSKIEJ SP Z O O", "cp_cowork", "rent_office", "matched"),
  txn("txn_s_kadr1110", "acc_pln", "2026-11-10", "4920.00", "KADROWNIA SP Z O O FV 2026/10/041", "cp_kadrownia", "revenue_services", "matched"),
  txn("txn_s_lis1110", "acc_pln", "2026-11-10", "-10500.00", "PIOTR LIS IT FV 10/2026", "cp_lis", "contractors", "matched"),
  txn("txn_s_figment1107", "acc_owner", "2026-11-07", "-61.65", "FIGMENT DESIGN", "cp_figment", "software_subscriptions", "matched", { ...card("9021"), original_amount: { amount: "-15.00", currency: "USD" } }),
  // October
  txn("txn_s_salary_jan", "acc_pln", "2026-10-30", "-5800.00", "JAN KOWALSKI WYNAGRODZENIE 10/2026", "cp_kowalski", "salaries", "no_document_needed", { transaction_type: "salary" }),
  txn("txn_s_salary_marta", "acc_pln", "2026-10-30", "-5800.00", "MARTA ZIELINSKA WYNAGRODZENIE 10/2026", "cp_zielinska", "salaries", "no_document_needed", { transaction_type: "salary" }),
  txn("txn_s_fee_tomasz", "acc_pln", "2026-10-30", "-4000.00", "TOMASZ BORSUK WYNAGRODZENIE ZARZADU", "cp_borsuk", "salaries", "no_document_needed", { transaction_type: "salary" }),
  txn("txn_s_mazur", "acc_pln", "2026-10-31", "-11200.00", "MAZUR STUDIO FV 10/2026", "cp_mazur", "contractors", "matched"),
  txn("txn_s_wrona", "acc_pln", "2026-10-31", "-10800.00", "WRONA DESIGN FV 2026/10", "cp_wrona", "contractors", "matched"),
  txn("txn_s_lis1031", "acc_pln", "2026-10-31", "-10500.00", "PIOTR LIS IT FV 09/2026", "cp_lis", "contractors", "matched"),
  txn("txn_s_dudek", "acc_pln", "2026-10-31", "-9900.00", "DUDEK DEV FV 10/2026", "cp_dudek", "contractors", "matched"),
  txn("txn_s_mebl", "acc_pln", "2026-10-27", "36900.00", "MEBLOSTYL FV 2026/09/037", "cp_meblostyl", "revenue_services", "matched"),
  txn("txn_s_vat_sep", "acc_pln", "2026-10-26", "-14300.00", "URZAD SKARBOWY VAT 09/2026", "cp_taxoffice", "taxes", "no_document_needed", { transaction_type: "tax" }),
  txn("txn_s_trattoria", "acc_pln", "2026-10-23", "-1800.00", "TRATTORIA MANUFAKTURA", "cp_trattoria", "meals_representation", "matched", card("4417")),
  txn("txn_s_flight", "acc_pln", "2026-10-22", "-2320.00", "SKYLINK AIRLINES LCJ-HAM", "cp_lot", "travel", "matched", card("4417")),
  txn("txn_s_pit_oct", "acc_pln", "2026-10-20", "-7300.00", "URZAD SKARBOWY PIT-4R CIT 09/2026", "cp_taxoffice", "taxes", "no_document_needed", { transaction_type: "tax" }),
  txn("txn_s_pixel_oct", "acc_pln", "2026-10-20", "-181.00", "PIXELBOARD.COM* SAN FRANCISCO", "cp_pixelboard", "software_subscriptions", "matched", { ...card("4417"), original_amount: { amount: "-45.00", currency: "USD" } }),
  txn("txn_s_card5521", "acc_pln", "2026-10-19", "-960.00", "CARD *5521 ZAKUP", null, "other", "missing_document", { ...card("5521"), data_quality: ["counterparty_unresolved"] }),
  txn("txn_s_laptop", "acc_pln", "2026-10-16", "-4850.00", "ELEKTROMARKT POLSKA LAPTOP", "cp_elektromarkt", "equipment", "matched", card("4417")),
  txn("txn_s_piek", "acc_pln", "2026-10-15", "8880.00", "PIEKARNIA ZLOTY KLOS FV 2026/09/039", "cp_piekarnia", "revenue_services", "matched"),
  txn("txn_s_zus", "acc_pln", "2026-10-15", "-9200.00", "ZAKLAD UBEZPIECZEN SPOLECZNYCH", "cp_zus", "social_security", "no_document_needed", { transaction_type: "social_security" }),
  txn("txn_s_cowork_oct", "acc_pln", "2026-10-14", "-2460.00", "BIURO NA PIOTRKOWSKIEJ SP Z O O", "cp_cowork", "rent_office", "matched"),
  txn("txn_s_rail_oct", "acc_pln", "2026-10-12", "-780.00", "RAILEXPRESS BILETY", "cp_rail", "travel", "matched", card("4417")),
  txn("txn_s_koszyk", "acc_pln", "2026-10-11", "-212.00", "KOSZYK 24 LODZ", "cp_koszyk", "other", "missing_document", card("4417")),
  txn("txn_s_allegro", "acc_pln", "2026-10-11", "-1240.00", "MARKETPLACE ORDER 88213-PL", "cp_allegro", "other", "missing_document", card("4417")),
  txn("txn_s_abakus", "acc_pln", "2026-10-10", "-1240.00", "ABAKUS BIURO RACHUNKOWE FV 10/2026", "cp_abakus", "professional_services", "matched"),
  txn("txn_s_kadr_oct", "acc_pln", "2026-10-10", "4920.00", "KADROWNIA SP Z O O FV 2026/09/033", "cp_kadrownia", "revenue_services", "matched"),
  txn("txn_s_taxigo", "acc_pln", "2026-10-09", "-95.00", "TAXIGO PRZEJAZD", "cp_taxigo", "other", "missing_document", card("4417")),
  txn("txn_s_parkuj", "acc_pln", "2026-10-08", "-105.00", "PARKUJ.PL", "cp_parkuj", "other", "missing_document", card("4417")),
  txn("txn_s_nordwind", "acc_eur", "2026-10-06", "18400.00", "NORDWIND LOGISTIK GMBH RE FV/09/07", "cp_nordwind", "revenue_services", "matched", { amount: { amount: "18400.00", currency: "EUR" }, amount_base: pln("81100.00") }),
  txn("txn_s_serwer", "acc_pln", "2026-10-05", "-11400.00", "SERWEROWNIA LODZ GPU 10/2026", "cp_serwer", "cloud_hosting", "matched"),
  txn("txn_s_mailbox", "acc_pln", "2026-10-04", "-143.00", "MAILBOX PRO", "cp_mailbox", "software_subscriptions", "matched", card("4417")),
  txn("txn_s_logbear", "acc_pln", "2026-10-03", "-324.00", "LOGBEAR.IO", "cp_logbear", "software_subscriptions", "matched", { ...card("4417"), original_amount: { amount: "-80.00", currency: "USD" } }),
  txn("txn_s_chmura", "acc_pln", "2026-10-02", "-1552.00", "CHMURA POLSKA SP Z O O", "cp_chmura", "cloud_hosting", "matched", card("4417")),
  txn("txn_s_rechenwerk", "acc_eur", "2026-10-01", "-58.90", "RECHENWERK GMBH", "cp_rechenwerk", "software_subscriptions", "matched", { amount: { amount: "-58.90", currency: "EUR" }, amount_base: pln("-260.00") }),
];

// What GET /people/costs, /clients and /subscriptions return for the sample company.
export const PEOPLE_COSTS: PeopleCosts & { items: (PeopleCosts["items"][number] & { parts?: { label: string; amount: Money }[] })[] } = {
  items: [
    { person_id: "per_tomasz", name: "Tomasz Borsuk (SAMPLE)", role: "owner", pay_type: "board_fee", paid: pln("6400.00"), payments: 2, owed: pln("0.00"), receipts_owed: 0, parts: [{ label: "fee", amount: pln("4000.00") }, { label: "social security", amount: pln("2400.00") }] },
    { person_id: "per_jan", name: "Jan Kowalski (SAMPLE)", role: "employee", pay_type: "salary", paid: pln("9200.00"), payments: 2, owed: pln("2059.00"), receipts_owed: 4, parts: [{ label: "salary", amount: pln("5800.00") }, { label: "social security", amount: pln("3400.00") }] },
    { person_id: "per_marta", name: "Marta Zielińska (SAMPLE)", role: "employee", pay_type: "salary", paid: pln("9200.00"), payments: 2, owed: pln("1640.00"), receipts_owed: 3, parts: [{ label: "salary", amount: pln("5800.00") }, { label: "social security", amount: pln("3400.00") }] },
    { person_id: "per_karolina", name: "Karolina Mazur (SAMPLE)", role: "contractor", pay_type: "invoice", paid: pln("11200.00"), payments: 1, owed: pln("0.00"), receipts_owed: 0 },
    { person_id: "per_anna", name: "Anna Wrona (SAMPLE)", role: "contractor", pay_type: "invoice", paid: pln("10800.00"), payments: 1, owed: pln("0.00"), receipts_owed: 0 },
    { person_id: "per_piotr", name: "Piotr Lis (SAMPLE)", role: "contractor", pay_type: "invoice", paid: pln("10500.00"), payments: 1, owed: pln("1470.00"), receipts_owed: 3 },
    { person_id: "per_michal", name: "Michał Dudek (SAMPLE)", role: "contractor", pay_type: "invoice", paid: pln("9900.00"), payments: 1, owed: pln("0.00"), receipts_owed: 0 },
  ],
  totals: { staff: pln("67200.00"), social_security: pln("9200.00"), share_of_costs: 0.54 },
};

const OPEN_INVOICES: ClientsResponse["items"] = [
  { counterparty_id: "cp_nordwind", name: "Nordwind Logistik GmbH (SAMPLE)", currency: "EUR", paid_in_month: pln("0.00"), open_invoices: [{ document_id: "doc_fv1007", number: "FV/10/07", gross: { amount: "18400.00", currency: "EUR" }, gross_base: pln("81100.00"), due_date: "2026-11-14", days_late: 7 }], open_total_base: pln("81100.00"), typical_payment_delay_days: 23, share_of_income: 0 },
  { counterparty_id: "cp_meblostyl", name: "Meblostyl (SAMPLE)", currency: "PLN", paid_in_month: pln("0.00"), open_invoices: [{ document_id: "doc_fv1042", number: "2026/10/042", gross: pln("36900.00"), gross_base: pln("36900.00"), due_date: "2026-11-27", days_late: 0 }], open_total_base: pln("36900.00"), typical_payment_delay_days: 0, share_of_income: 0 },
  { counterparty_id: "cp_piekarnia", name: "Piekarnia Złoty Kłos (SAMPLE)", currency: "PLN", paid_in_month: pln("0.00"), open_invoices: [{ document_id: "doc_fv1043", number: "2026/10/043", gross: pln("6610.00"), gross_base: pln("6610.00"), due_date: "2026-12-14", days_late: 0 }], open_total_base: pln("6610.00"), typical_payment_delay_days: 1, share_of_income: 0 },
  { counterparty_id: "cp_kadrownia", name: "Kadrownia sp. z o.o. (SAMPLE)", currency: "PLN", paid_in_month: pln("0.00"), open_invoices: [{ document_id: "doc_fv1148", number: "2026/11/048", gross: pln("4920.00"), gross_base: pln("4920.00"), due_date: "2026-11-18", days_late: 3 }], open_total_base: pln("4920.00"), typical_payment_delay_days: 2, share_of_income: 0 },
  { counterparty_id: "cp_lakeshore", name: "Lakeshore Robotics Inc. (SAMPLE)", currency: "USD", paid_in_month: pln("0.00"), open_invoices: [{ document_id: "doc_fvlake01", number: "2026/11/051", gross: { amount: "40000.00", currency: "USD" }, gross_base: pln("162450.00"), due_date: "2027-01-05", days_late: 0 }], open_total_base: pln("162450.00"), typical_payment_delay_days: null, share_of_income: 0 },
];
/** Paid per client and month: [paid, share of that month's income]. */
const CLIENT_PAID: Record<string, Record<string, [string, number]>> = {
  "2026-10": { cp_nordwind: ["81100.00", 0.62], cp_meblostyl: ["36900.00", 0.28], cp_piekarnia: ["8880.00", 0.07], cp_kadrownia: ["4920.00", 0.04] },
  "2026-11": { cp_kadrownia: ["4920.00", 1] },
  "2026-09": { cp_nordwind: ["76500.00", 0.65], cp_meblostyl: ["29400.00", 0.25], cp_piekarnia: ["6880.00", 0.06], cp_kadrownia: ["4920.00", 0.04] },
};
export function clientsFor(month: string): ClientsResponse {
  const paid = CLIENT_PAID[month] ?? {};
  const items = OPEN_INVOICES.map((c) => ({ ...c, paid_in_month: pln(paid[c.counterparty_id]?.[0] ?? "0.00"), share_of_income: paid[c.counterparty_id]?.[1] ?? 0 }));
  const total = Object.values(paid).reduce((s, [a]) => s + BigInt(a.replace(".", "")), 0n);
  return { items, totals: { paid_in_month: pln(`${total / 100n}.${String(total % 100n).padStart(2, "0")}`), open_base: pln("291980.00"), late_base: pln("86020.00") } };
}

export const SUBSCRIPTIONS: SubscriptionsResponse = {
  items: [
    { counterparty_id: "cp_chmura", name: "Chmura Polska (SAMPLE)", category: "cloud_hosting", monthly: pln("1552.00"), original: null, previous_monthly: pln("1386.00"), paid_by: [{ kind: "card", label: "Company card ending 4417" }], flags: ["price_up"], series_ids: ["ser_chmura"] },
    { counterparty_id: "cp_logbear", name: "LogBear (SAMPLE)", category: "software_subscriptions", monthly: pln("324.00"), original: { amount: "80.00", currency: "USD" }, paid_by: [{ kind: "card", label: "Company card ending 4417" }], flags: [], series_ids: ["ser_logbear"] },
    { counterparty_id: "cp_rechenwerk", name: "Rechenwerk (SAMPLE)", category: "software_subscriptions", monthly: pln("260.00"), original: { amount: "58.90", currency: "EUR" }, paid_by: [{ kind: "account", label: "Company account EUR" }], flags: [], series_ids: ["ser_rechenwerk"] },
    { counterparty_id: "cp_pixelboard", name: "PixelBoard Inc. (SAMPLE)", category: "software_subscriptions", monthly: pln("181.00"), original: { amount: "45.00", currency: "USD" }, paid_by: [{ kind: "card", label: "Company card ending 4417" }], flags: [], series_ids: ["ser_pixelboard"] },
    { counterparty_id: "cp_taskpilot", name: "TaskPilot (SAMPLE)", category: "software_subscriptions", monthly: pln("178.00"), original: null, duplicate_cost: pln("89.00"), paid_by: [{ kind: "person", label: "Jan's card" }, { kind: "person", label: "Marta's card" }], flags: ["paid_twice"], series_ids: ["ser_taskpilot_jan", "ser_taskpilot_marta"] },
    { counterparty_id: "cp_mailbox", name: "Mailbox Pro (SAMPLE)", category: "software_subscriptions", monthly: pln("143.00"), original: null, paid_by: [{ kind: "card", label: "Company card ending 4417" }], flags: [], series_ids: ["ser_mailbox"] },
    { counterparty_id: "cp_figment", name: "Figment Design (SAMPLE)", category: "software_subscriptions", monthly: pln("62.00"), original: { amount: "15.00", currency: "USD" }, paid_by: [{ kind: "person", label: "Owner's private card" }], flags: ["paid_privately"], series_ids: ["ser_figment"] },
  ],
  monthly_total: pln("2700.00"),
};

/** What else repeats every month, for Money › Monthly payments (scope=all). In November not all of it is paid yet. */
export const MONTHLY_EXTRA: SubscriptionsResponse["items"] = [
  { counterparty_id: "cp_cowork", name: "Coworking space (SAMPLE)", category: "rent_office", monthly: pln("2460.00"), original: null, paid_by: [{ kind: "account", label: "Company account PLN" }], flags: [], series_ids: [], paid_in_month: true },
  { counterparty_id: "cp_kowalski", name: "Jan Kowalski (SAMPLE)", category: "salaries", monthly: pln("5800.00"), original: null, paid_by: [{ kind: "account", label: "Company account PLN" }], flags: [], series_ids: [], paid_in_month: false },
  { counterparty_id: "cp_zielinska", name: "Marta Zielińska (SAMPLE)", category: "salaries", monthly: pln("5800.00"), original: null, paid_by: [{ kind: "account", label: "Company account PLN" }], flags: [], series_ids: [], paid_in_month: false },
  { counterparty_id: "cp_lis", name: "Piotr Lis (SAMPLE)", category: "contractors", monthly: pln("10500.00"), original: null, paid_by: [{ kind: "account", label: "Company account PLN" }], flags: [], series_ids: [], paid_in_month: true },
  { counterparty_id: "cp_zus", name: "Social security office (SAMPLE)", category: "social_security", monthly: pln("9200.00"), original: null, paid_by: [{ kind: "account", label: "Company account PLN" }], flags: [], series_ids: [], paid_in_month: false },
  { counterparty_id: "cp_abakus", name: "Abakus accounting office (SAMPLE)", category: "professional_services", monthly: pln("1240.00"), original: null, paid_by: [{ kind: "account", label: "Company account PLN" }], flags: [], series_ids: [], paid_in_month: false },
];

// Settings, people and learned rules (GET /settings, /people, /rules).
export const SETTINGS: Settings = {
  company: { id: "co_borsuk", name: "Borsuk Labs sp. z o.o. (SAMPLE)", tax_id: "999-000-00-14", base_currency: "PLN", vat_period: "monthly", accountant_email: "office@abakus.example" },
  alerts: { safety_buffer: pln("10000.00"), late_client_days: 7, weekly_summary: true },
};
const person = (id: string, name: string, email: string, role: string, pay_type: string, card_last4: string[], statement_names: string[]): Person =>
  ({ id, name, email, role, pay_type, card_last4, statement_names, tax_id: null, iban: null });
export const PEOPLE: Person[] = [
  person("per_tomasz", "Tomasz Borsuk (SAMPLE)", "owner@borsuk-labs.sample", "owner", "board_fee", ["9021"], ["TOMASZ BORSUK"]),
  person("per_jan", "Jan Kowalski (SAMPLE)", "jan@borsuk-labs.sample", "employee", "salary", ["7730"], ["JAN KOWALSKI"]),
  person("per_marta", "Marta Zielińska (SAMPLE)", "marta@borsuk-labs.sample", "employee", "salary", ["3318"], ["MARTA ZIELINSKA"]),
  person("per_piotr", "Piotr Lis (SAMPLE)", "piotr@lis-it.sample", "contractor", "invoice", ["6042"], ["PIOTR LIS IT"]),
  person("per_anna", "Anna Wrona (SAMPLE)", "anna@wrona-design.sample", "contractor", "invoice", [], ["WRONA DESIGN"]),
  person("per_karolina", "Karolina Mazur (SAMPLE)", "karolina@mazur-studio.sample", "contractor", "invoice", [], ["MAZUR STUDIO"]),
  person("per_michal", "Michał Dudek (SAMPLE)", "michal@dudek-dev.sample", "contractor", "invoice", [], ["DUDEK DEV"]),
];
export const RULES: Rule[] = [
  { id: "rule_koszyk", raw: "KOSZYK 24", counterparty_id: "cp_koszyk", counterparty_name: "Koszyk 24 (SAMPLE)", category: "owner_private", learned_at: "2026-11-12T09:12:00Z" },
  { id: "rule_pixel", raw: "PIXELBOARD.COM* SAN FRANCISCO", counterparty_id: "cp_pixelboard", counterparty_name: "PixelBoard Inc. (SAMPLE)", category: "software_subscriptions", learned_at: "2026-10-03T14:40:00Z" },
  { id: "rule_lis", raw: "PIOTR LIS IT", counterparty_id: "cp_lis", counterparty_name: "Piotr Lis (SAMPLE)", category: "contractors", learned_at: "2026-09-28T08:05:00Z" },
  { id: "rule_chmura", raw: "CHMURA POLSKA", counterparty_id: "cp_chmura", counterparty_name: "Chmura Polska (SAMPLE)", category: "cloud_hosting", learned_at: "2026-09-02T11:30:00Z" },
];

// Chat history (GET /chat/sessions, /chat/sessions/{id}).
type Msg = ChatSessionDetail["messages"][number];
const turn = (at: string, question: string, answer: string): Msg[] => [{ role: "user", content: question, at }, { role: "assistant", content: answer, at }];
export const CHAT_HISTORY: (ChatSession & { detail: Msg[] })[] = [
  { session_id: "chat_jan", title: "What does Jan cost us?", last_at: "2026-11-21T09:44:00Z", messages: 4, detail: [
    ...turn("2026-11-21T09:42:00Z", "What does Jan cost us per month?", "In October Jan cost 9,200 PLN: 5,800 PLN salary and 3,400 PLN social security. He also paid 2,059 PLN for company things with his own card, which you still owe him."),
    ...turn("2026-11-21T09:44:00Z", "And what if I hire a developer for 15,000 PLN a month from January?", "Then cash goes below zero on 30 January, about 9,400 PLN short. It is back above zero on 7 February, when Nordwind usually pays."),
  ] },
  { session_id: "chat_costs", title: "Why were costs higher in October?", last_at: "2026-11-20T16:05:00Z", messages: 2, detail: turn("2026-11-20T16:05:00Z", "Why were costs higher in October?", "October costs were 124,600 PLN, 4,800 PLN more than in September. The biggest reason is a new laptop for 4,850 PLN. Payments without an explanation went down by 2,800 PLN.") },
  { session_id: "chat_owed", title: "Who still owes us money?", last_at: "2026-11-20T09:31:00Z", messages: 2, detail: turn("2026-11-20T09:31:00Z", "Who still owes us money?", "Clients owe you 291,980 PLN. 86,020 PLN of it is late: Nordwind (18,400 EUR, 7 days late) and Kadrownia (4,920 PLN, 3 days late).") },
  { session_id: "chat_vat", title: "VAT for November", last_at: "2026-11-13T15:20:00Z", messages: 2, detail: turn("2026-11-13T15:20:00Z", "How much VAT will we pay for November?", "So far about 9,800 PLN. It is due on 25 December. 242.90 PLN of VAT is lost because one receipt has no company tax number.") },
  { session_id: "chat_twice", title: "Tools we pay for twice", last_at: "2026-11-11T12:02:00Z", messages: 2, detail: turn("2026-11-11T12:02:00Z", "Do we pay for any tool twice?", "Yes: TaskPilot is paid by Jan and by Marta, 89 PLN each. One plan is enough.") },
  { session_id: "chat_bonus", title: "Can I afford a December bonus?", last_at: "2026-11-09T18:45:00Z", messages: 2, detail: turn("2026-11-09T18:45:00Z", "Can I afford a 10,000 PLN bonus in December?", "Not before 7 December: cash is below zero from 30 November until Nordwind pays. After that you would still keep about 63,000 PLN.") },
];

// Extra agent cards, so To-do shows every kind of item the agents create.
const why = (lines: string[], extra: Partial<Recommendation["explanation"]> = {}): Recommendation["explanation"] =>
  ({ why: lines, confidence: 0.8, generated_by: { numbers: "finance-engine", wording: "template", trace_id: null }, ...extra });
const card0 = (r: Partial<Recommendation> & Pick<Recommendation, "id" | "agent" | "type" | "title" | "summary" | "control_level" | "evidence">): Recommendation => ({
  company_id: "co_borsuk", execution_mode: r.control_level === "approval_required" ? "simulated" : "none", status: "new", severity: "info",
  created_at: "2026-11-21T10:15:00Z", explanation: why([]), ...r,
});
const forecastLink = { kind: "forecast" as const, id: "fc_20261121a", label: "45-day forecast of 21 Nov", url: "/" };
export const SAMPLE_RECOMMENDATIONS: Recommendation[] = [
  card0({
    id: "rec_chase01", agent: "liquidity", type: "chase_receivable", control_level: "approval_required", severity: "warning",
    title: "Remind Nordwind to pay", summary: "Ordo writes a friendly reminder. You read it before it is sent.",
    explanation: why(["Invoice FV/10/07 for 18,400 EUR was due on 14 Nov and is 7 days late", "Nordwind usually pays 23 days late; a reminder can bring the money in before 30 Nov"]),
    evidence: [forecastLink, { kind: "external", id: "cp_nordwind", label: "Nordwind's open invoices", url: "/money/clients" }],
    proposed_action: { kind: "send_email_draft", params: { to: "accounts@nordwind.example", subject: "Invoice FV/10/07" }, preview: "SIMULATED: no e-mail leaves the app in this build." },
    impact: { cost: pln("0.00") },
  }),
  card0({
    id: "rec_defer01", agent: "liquidity", type: "payment_deferral", control_level: "approval_required", severity: "warning",
    title: "Pay contractors on 8 Dec instead of 30 Nov", summary: "Ordo drafts a short note to the 4 contractors. They have to agree.",
    explanation: why(["Contractor invoices of 42,400 PLN are due on 30 Nov", "Paying them on 8 Dec, after Nordwind pays, avoids the gap without bank costs"]),
    evidence: [forecastLink],
    proposed_action: { kind: "send_email_draft", params: { to: "4 contractors", pay_on: "2026-12-08" }, preview: "SIMULATED: no e-mail leaves the app in this build." },
    impact: { cost: pln("0.00") },
  }),
  card0({
    id: "rec_private01", agent: "ingestion", type: "mark_private", control_level: "recommendation",
    title: "3 company-card payments look personal", summary: "Koszyk 24, Taxigo and Parkuj.pl. 412 PLN in total.",
    explanation: why(["A grocery shop, a taxi and parking, paid with the company card on a weekend", "None of them has an invoice"]),
    evidence: [{ kind: "transaction", id: "txn_s_koszyk", label: "Koszyk 24", url: "/money/payments/txn_s_koszyk?month=2026-10" }],
  }),
  card0({
    id: "rec_missing01", agent: "ingestion", type: "missing_document", control_level: "recommendation",
    title: "24 payments have no invoice", summary: "7,800 PLN in October. The biggest is a marketplace order, 1,240 PLN.",
    explanation: why(["Without an invoice a cost cannot go into the books, and its VAT cannot be reclaimed"]),
    evidence: [{ kind: "external", id: "missing", label: "Payments without an invoice", url: "/money/payments?month=2026-10&doc=missing" }],
  }),
  card0({
    id: "rec_vatname01", agent: "tax", type: "request_company_invoice", control_level: "recommendation",
    title: "5 receipts are in an employee's name", summary: "1,140 PLN of VAT lost. Next time ask for an invoice to Borsuk Labs, tax no. 999-000-00-14.",
    explanation: why(["A receipt without the company's tax number does not allow a VAT deduction"]),
    evidence: [{ kind: "document", id: "doc_rcpt412", label: "Jan's monitor receipt", url: "/documents/doc_rcpt412" }],
  }),
  card0({
    id: "rec_640", agent: "ingestion", type: "reimburse_employee", control_level: "approval_required", status: "executed_simulated", approval_id: "apr_s640",
    created_at: "2026-11-18T08:30:00Z", title: "Pay Marta back 640.00 PLN", summary: "Marta paid for printer toner and paper with her own card.",
    explanation: why(["The receipts were forwarded by Marta and are not on any company account"]),
    evidence: [{ kind: "external", id: "per_marta", label: "Marta's receipts", url: "/money/people" }],
    proposed_action: { kind: "create_payment_draft", params: { to: "per_marta", amount: pln("640.00"), pay_on: "2026-11-18" } },
  }),
];
export const SAMPLE_APPROVALS: Approval[] = [{
  id: "apr_s640", subject_type: "recommendation", subject_id: "rec_640", decision: "approved",
  decided_by: { name: "Tomasz Borsuk (SAMPLE)", role: "owner" }, decided_at: "2026-11-18T09:02:00Z", channel: "dashboard", comment: null, changes: null,
  execution: { mode: "simulated", status: "done", executed_at: "2026-11-18T09:02:01Z", reference: "SIM-PD-2026-0398", result: "Sandbox bank added a transfer draft of 640.00 PLN to Marta.", effects: [] },
}];

// What Ordo reads from a file the owner adds, standing in for the extractor.
const cents = (amount: string) => BigInt(amount.replace("-", "").replace(".", ""));
const fromCents = (c: bigint) => `${c / 100n}.${String(c % 100n).padStart(2, "0")}`;
export function readUpload(docId: string, rawId: string, t: Transaction | undefined, sellerName: string): OrdoDocument {
  const sklepik = t?.id === "txn_s_sklepik";
  const gross = t ? cents(t.amount_base.amount) : 184000n;
  const vat = (gross * 23n + 61n) / 123n; // 23% VAT inside the gross amount, rounded to the cent
  return {
    id: docId, company_id: "co_borsuk", raw_item_ids: [rawId], doc_type: "invoice", direction: "purchase", channel: "upload",
    number: sklepik ? "FV 2026/11/0187" : "FV 2026/11/0112", issue_date: t?.booking_date ?? "2026-11-18", due_date: t?.booking_date ?? "2026-11-18",
    seller: { name: sklepik ? "Sklepik.pl sp. z o.o. (SAMPLE)" : sellerName, tax_id: sklepik ? "999-000-00-71" : "999-000-00-77", country: "PL" },
    buyer: { name: "Borsuk Labs sp. z o.o. (SAMPLE)", tax_id: "999-000-00-14", country: "PL", is_company: true },
    totals: { net: pln(fromCents(gross - vat)), vat: pln(fromCents(vat)), gross: pln(fromCents(gross)), gross_base: pln(fromCents(gross)) },
    lines: sklepik ? [{ description: "Office chair", quantity: 2, unit_price: "920.00" }] : [{ description: "Purchase", quantity: 1, unit_price: fromCents(gross) }],
    payment: { method: "card", card_last4: t?.card_last4 ?? null, paid: true, paid_date: t?.booking_date ?? null },
    submitted_by: { name: "Tomasz Borsuk (SAMPLE)", email: "owner@borsuk-labs.sample", role: "owner" },
    extraction: { method: "docling_llm", model: "sample", confidence: 0.9, field_confidence: { number: 0.62, gross: 0.98, vat: 0.97, issue_date: 0.96, seller_tax_id: 0.95, buyer_tax_id: 0.97 }, warnings: [], trace_id: null },
    category_suggestion: { category: sklepik ? "equipment" : (t?.category && t.category !== "other" ? t.category : "equipment"), confidence: 0.88, method: "llm" },
    status: "needs_review", flags: ["low_confidence"], created_at: "2026-11-21T10:20:00Z",
  };
}
