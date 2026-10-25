# O4U backend (development only)

Supabase-compatible PostgreSQL: catalogue, size-level stock, an append-only stock ledger, the website-order lifecycle,
counter-sale (POS) foundations, and role enforcement. Not connected to anything real; synthetic data only.
Design and status: `Claude outputs/O4U_Order_Operations_Design.md`.

```
migrations/0001_core.sql      the schema and every function (the only file that would ever be applied)
tests/supabase_shim.sql       TEST ONLY stand-ins for Supabase roles and auth.uid()
tests/run_db_tests.py         33 checks on a throwaway local PostgreSQL 16 with invented data
```

Run the checks (needs Python 3.10+; downloads a PostgreSQL build into a virtual environment, touches nothing else):

```
python -m venv backend/.venv
backend/.venv/Scripts/pip install pgserver "psycopg[binary]"
backend/.venv/Scripts/python backend/tests/run_db_tests.py
```

Rules this code must keep: stock changes only through `apply_stock_event`; every mutating function takes an
idempotency key; money is integer paise; nothing here is applied to a real project without the owner's approval.
