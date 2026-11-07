# Live signal ingestion

From the repository root, after `spacetime login`:

```bash
PYTHONPATH=. python scripts/ingest_ercot.py --database shiftos --zone HB_NORTH
```

This fetches ERCOT's public 15-minute real-time settlement point table and
writes each observation through the `ingest_price` SpacetimeDB reducer.
