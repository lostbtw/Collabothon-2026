import { describe, expect, it } from "vitest";
import { formatMoney, isNegative } from "./money";

describe("formatMoney", () => {
  it("groups thousands and keeps two decimals", () => {
    expect(formatMoney({ amount: "1299.00", currency: "PLN" })).toBe("1,299.00 PLN");
    expect(formatMoney({ amount: "38400", currency: "PLN" })).toBe("38,400.00 PLN");
  });
  it("keeps the sign and never rounds through a float", () => {
    expect(formatMoney({ amount: "-7870.00", currency: "PLN" })).toBe("-7,870.00 PLN");
    expect(formatMoney({ amount: "9007199254740993.10", currency: "EUR" })).toBe("9,007,199,254,740,993.10 EUR");
  });
  it("can hide decimals and handles a missing value", () => {
    expect(formatMoney({ amount: "-7870.00", currency: "PLN" }, { decimals: false })).toBe("-7,870 PLN");
    expect(formatMoney(null)).toBe("—");
  });
  it("detects negative amounts", () => {
    expect(isNegative({ amount: "-0.00", currency: "PLN" })).toBe(false);
    expect(isNegative({ amount: "-1.00", currency: "PLN" })).toBe(true);
  });
});
