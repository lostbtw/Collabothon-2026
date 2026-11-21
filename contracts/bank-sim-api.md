# Sandbox Bank simulator API (the bank the demo polls)

A tiny service we run on the cluster. It behaves like a bank's PSD2 account-information API so that the bank
connector is a real polling client, and the same connector code can be pointed at a third-party sandbox.
Shape follows Berlin Group NextGenPSD2 AIS naming (`/v1/accounts`, `transactions.booked[]`, `entryReference`,
`transactionAmount`, `remittanceInformationUnstructured`). It is **not** a certified implementation.

Auth: `Authorization: Bearer <static token from Secret>` + header `Consent-ID: demo`.

| Method and path | Purpose |
|---|---|
| `GET /v1/accounts` | List accounts: `resourceId, iban, currency, name, ownerName, cashAccountType` |
| `GET /v1/accounts/{id}/balances` | `balances[]` with `balanceType: closingBooked`, `balanceAmount`, `referenceDate` |
| `GET /v1/accounts/{id}/transactions?bookingStatus=booked&dateFrom=YYYY-MM-DD&entryReferenceFrom=E000000731` | Booked lines **after** the given entry reference (delta). Returns `transactions.booked[]` and `_links.next` |
| `POST /v1/credit-line-applications` | Simulated execution target: `{accountId, limit, tenorDays}` -> `{reference: "SIM-CL-...", status: "accepted", availableFrom}` |
| `POST /v1/fx-forwards` | Simulated execution target for FX Shield: `{accountId, sellCurrency, buyCurrency, notional, rate, valueDate}` -> `{reference: "SIM-FX-...", status: "booked"}` |
| `POST /v1/payment-drafts` | Simulated execution target for reimbursements: `{debtorAccount, creditorName, amount, remittance, requestedExecutionDate}` -> `{reference, status: "draft"}` |
| `POST /admin/transactions` | Generator only: inject one booked line `{accountId, bookingDate, amount, currency, creditorName/debtorName, remittance, cardLast4?}` |
| `POST /admin/load-csv?profile=commerzbank_csv&accountId=` | Load the organisers' pizzeria CSV as an account (keeps CHF quirk as-is, so the normaliser must fix it) |

Booked line example:

```json
{"entryReference":"E000000731","bookingDate":"2026-11-20","valueDate":"2026-11-19",
 "transactionAmount":{"amount":"-180.62","currency":"PLN"},
 "creditorName":"PIXELBOARD.COM* SAN FRANCISCO",
 "remittanceInformationUnstructured":"PIXELBOARD.COM* SAN FRANCISCO 45.00 USD KARTA *4417",
 "proprietaryBankTransactionCode":"CARD_PAYMENT"}
```

Rules: `entryReference` is strictly increasing per account (the connector's cursor). Lines are never edited; a correction is a new line.
