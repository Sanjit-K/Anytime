# ShiftOS SpacetimeDB module

This module is the live backend for price signals, demand signals, workloads, schedules, and post-task telemetry. SpacetimeDB tables provide real-time subscriptions; reducers are the only write path.

## Local development

Install the [SpacetimeDB CLI](https://spacetimedb.com/docs/), then run:

```bash
npm install
cd ..
spacetime build -p spacetime
```

From the repository root, publish this module with:

```bash
spacetime login
spacetime publish -p spacetime shiftos
```

The `-p spacetime` flag is important because this repository keeps the module in `spacetime/` rather than the default `spacetimedb/` directory.
