"""Build standin_rates.json: the NBP table the pipeline uses until role 2's NBP connector (#34) lands.

Rates come from role 4's scenario (sim/scenario/bank_2026.py `mid_rate`), the rate its card lines are priced with,
on its bank days (weekdays without Polish holidays), so foreign documents match the scenario's bank lines.
One override: USD on 18 Nov 2026 is 3.9099, the NBP rate in contracts/fixtures (doc_pixel11 / txn_731) that the
PixelBoard demo line was built from.

    python backend/pipeline/normalise/build_standin_rates.py      # rewrites standin_rates.json (deterministic)
"""
import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).with_name("standin_rates.json")
FIRST, LAST = date(2025, 11, 1), date(2026, 12, 31)
OVERRIDES = {("USD", "2026-11-18"): "3.9099"}


def main() -> None:
    folder = ROOT / "sim" / "scenario"
    sys.path.insert(0, str(folder))
    spec = importlib.util.spec_from_file_location("scenario_bank_2026", folder / "bank_2026.py")
    bank = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bank)
    table: dict[str, dict[str, str]] = {"USD": {}, "EUR": {}}
    day = FIRST
    while day <= LAST:
        if day.weekday() < 5 and day not in bank.HOLIDAYS:
            for ccy in table:
                table[ccy][day.isoformat()] = OVERRIDES.get((ccy, day.isoformat()), f"{bank.mid_rate(ccy, day):.4f}")
        day += timedelta(days=1)
    payload = {"_comment": "STAND-IN NBP table A mid rates (PLN per unit), built by build_standin_rates.py from "
                           "role 4's scenario; replaced by role 2's NBP connector (#34). Not real NBP rates.",
               **table}
    OUT.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({sum(len(v) for v in table.values())} rates)")


if __name__ == "__main__":
    main()
