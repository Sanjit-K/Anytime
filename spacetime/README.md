# ShiftOS SpacetimeDB module

This module is the live backend for price signals, demand signals, workloads, schedules, and post-task telemetry. SpacetimeDB tables provide real-time subscriptions; reducers are the only write path.

## Local development

Install the [SpacetimeDB CLI](https://spacetimedb.com/docs/), then run:

```bash
spacetime start
spacetime dev
```

The current docs use `spacetime dev --template basic-ts` for a fresh TypeScript module. Publish this module with `spacetime publish shiftos` when logged in.
