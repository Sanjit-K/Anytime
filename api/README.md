# ShiftOS API

Run from the repository root:

```bash
python -m pip install fastapi uvicorn
uvicorn api.main:app --reload
```

Then open `http://127.0.0.1:8000/docs` and POST a scenario to `/schedule`.

The endpoint compares immediate execution with a simple price-aware schedule
that places flexible jobs in their cheapest deadline-safe window and protects
the battery reserve. The scheduling function is an adapter seam for the full
optimizer in `engine/`.
