"""`python -m backend.db migrate|seed|setup|fixtures`; setup = migrate + seed, fixtures = setup + demo data."""
import sys

import psycopg

from backend.db.fixtures import load_fixtures
from backend.db.migrate import migrate
from backend.db.seed import seed
from backend.settings import database_url


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "setup"
    if command not in {"migrate", "seed", "setup", "fixtures"}:
        print("usage: python -m backend.db [migrate|seed|setup|fixtures]", file=sys.stderr)
        return 2
    with psycopg.connect(database_url()) as conn:
        if command in {"migrate", "setup", "fixtures"}:
            applied = migrate(conn)
            print("migrations applied:", ", ".join(applied) or "none (up to date)")
        if command in {"seed", "setup"}:
            seed(conn)
            print("seeded companies and people")
        if command == "fixtures":
            load_fixtures(conn)
            print("loaded contracts/fixtures as demo data")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
