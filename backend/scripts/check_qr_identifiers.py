"""
Read-only check of devices.qr_identifier values (B3.1, review finding 1).

Run it on a database BEFORE relying on the QR lookup introduced in B3.1. The lookup matches
a scan exactly as scanned, upper-cased or lower-cased (`qr_identifier IN (...)`), comparing
the column itself so the unique index stays usable. A stored value can only be missed if
it is MIXED case (e.g. "Qr-Abc", possible only when written directly in SQL) and is then
scanned in a different case. This script lists such rows and anything else the lookup
would not handle as expected.

STRICTLY READ-ONLY: the connection is opened with PostgreSQL's
`default_transaction_read_only = on`, so the server itself rejects any write, and the
transaction is rolled back at the end. Fixing a reported value is a data change for the
database owner to approve; nothing is changed here.

Run from the backend/ directory (the module path is `scripts.`):
    cd backend
    python -m scripts.check_qr_identifiers

Only DATABASE_URL is needed. It is read from the environment or, if unset there, from the
repository-root .env (the same file the API reads). JWT_SECRET_KEY is NOT required.

Exit codes: 0 = nothing to fix, 1 = issues listed, 2 = DATABASE_URL missing.
"""
import os
import sys
from typing import Callable

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from app.core.config import REPO_ROOT

# Every check sees only non-blank values except the first, so no row is counted twice.
NOT_BLANK = r"qr_identifier !~ '^\s*$'"
CHECKS = {
    "empty or whitespace-only (cannot be scanned at all)":
        r"qr_identifier ~ '^\s*$'",
    "mixed case (found only when scanned in exactly this case)":
        f"{NOT_BLANK} AND qr_identifier <> upper(qr_identifier) AND qr_identifier <> lower(qr_identifier)",
    "leading/trailing whitespace (scans are trimmed, so never matched)":
        rf"{NOT_BLANK} AND qr_identifier ~ '^\s|\s$'",
    "characters outside A-Z a-z 0-9 . _ - (the API's allowed set)":
        f"{NOT_BLANK} AND qr_identifier !~ '^[A-Za-z0-9._-]+$'",
}
SHOW = 50  # rows listed per check


def read_only_engine(database_url: str) -> Engine:
    """An engine whose every transaction is READ ONLY, enforced by PostgreSQL."""
    return create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"options": "-c default_transaction_read_only=on"},
    )


def run_checks(conn: Connection, out: Callable[[str], None] = print) -> int:
    """Runs every check on an open connection and returns the number of issues found."""
    issues = 0
    total = conn.execute(text("SELECT count(*) FROM devices")).scalar()
    lower_only = conn.execute(text(
        f"SELECT count(*) FROM devices WHERE {NOT_BLANK} "
        "AND qr_identifier <> upper(qr_identifier) AND qr_identifier = lower(qr_identifier)"
    )).scalar()
    out(f"Devices checked: {total}")
    out(f"Lower-case values (still found by the lookup, not an issue): {lower_only}")

    for label, condition in CHECKS.items():
        rows = conn.execute(text(
            f"SELECT id, device_code, qr_identifier FROM devices WHERE {condition} ORDER BY device_code"
        )).all()
        out(f"{label}: {len(rows)}")
        for r in rows[:SHOW]:
            out(f"    device {r.id}  code={r.device_code}  qr={r.qr_identifier!r}")
        issues += len(rows)

    clashes = conn.execute(text(
        f"SELECT upper(btrim(qr_identifier)) AS qr, count(*) AS n FROM devices WHERE {NOT_BLANK} "
        "GROUP BY upper(btrim(qr_identifier)) HAVING count(*) > 1 ORDER BY 1"
    )).all()
    out(f"values that differ only by case or spacing (ambiguous scans): {len(clashes)}")
    for r in clashes[:SHOW]:
        out(f"    {r.qr!r} x{r.n}")
    issues += len(clashes)
    return issues


def main() -> int:
    load_dotenv(REPO_ROOT / ".env", override=False)  # real environment variables win
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set (environment or repository-root .env).", file=sys.stderr)
        return 2

    engine = read_only_engine(url)
    try:
        with engine.connect() as conn:
            issues = run_checks(conn)
            conn.rollback()  # nothing was written; end the read-only transaction cleanly
    finally:
        engine.dispose()

    print("OK - no QR identifier needs attention." if issues == 0 else f"{issues} issue(s) found - see above.")
    return 0 if issues == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
