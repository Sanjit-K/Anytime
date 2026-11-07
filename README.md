# ShiftOS engine

The engine contains the hackathon MVP scheduler. Run tests from this directory with:

```bash
python -m unittest discover -s tests
```

`baseline(scenario)` runs workloads immediately without storage arbitrage. `optimize(scenario)` uses a transparent greedy policy to move flexible workloads into low-price slots and charge/discharge the configured battery.
