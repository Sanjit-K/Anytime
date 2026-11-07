import { schema, table, t } from 'spacetimedb/server';

const priceSignal = table({ name: 'price_signal', public: true }, {
  id: t.u64().primaryKey().autoInc(), region: t.string(), slot: t.u32(), price: t.f64(), source: t.string(), observedAt: t.string(),
});
const demandSignal = table({ name: 'demand_signal', public: true }, {
  id: t.u64().primaryKey().autoInc(), region: t.string(), slot: t.u32(), loadKw: t.f64(), newsImpact: t.f64(), confidence: t.f64(), source: t.string(),
});
const workload = table({ name: 'workload', public: true }, {
  id: t.string().primaryKey(), name: t.string(), powerKw: t.f64(), durationSlots: t.u32(), deadlineSlot: t.u32(), critical: t.bool(), status: t.string(),
});
const schedule = table({ name: 'schedule', public: true }, {
  runId: t.string().primaryKey(), createdAt: t.string(), baselineCost: t.f64(), optimizedCost: t.f64(), savings: t.f64(), status: t.string(), planJson: t.string(),
});
const taskRun = table({ name: 'task_run', public: true }, {
  id: t.u64().primaryKey().autoInc(), workloadId: t.string(), actualEnergyKwh: t.f64(), actualDurationSlots: t.u32(), completedSlot: t.u32(), success: t.bool(), recordedAt: t.string(),
});

const spacetimedb = schema({ priceSignal, demandSignal, workload, schedule, taskRun });
export default spacetimedb;

export const ingestPrice = spacetimedb.reducer({ region: t.string(), slot: t.u32(), price: t.f64(), source: t.string(), observedAt: t.string() }, (ctx, value) => {
  ctx.db.priceSignal.insert({ id: 0n, ...value });
});
export const ingestDemand = spacetimedb.reducer({ region: t.string(), slot: t.u32(), loadKw: t.f64(), newsImpact: t.f64(), confidence: t.f64(), source: t.string() }, (ctx, value) => {
  ctx.db.demandSignal.insert({ id: 0n, ...value });
});
export const upsertWorkload = spacetimedb.reducer({ id: t.string(), name: t.string(), powerKw: t.f64(), durationSlots: t.u32(), deadlineSlot: t.u32(), critical: t.bool(), status: t.string() }, (ctx, value) => {
  const existing = ctx.db.workload.id.find(value.id);
  if (existing) ctx.db.workload.id.update(value); else ctx.db.workload.insert(value);
});
export const publishSchedule = spacetimedb.reducer({ runId: t.string(), createdAt: t.string(), baselineCost: t.f64(), optimizedCost: t.f64(), savings: t.f64(), status: t.string(), planJson: t.string() }, (ctx, value) => {
  ctx.db.schedule.insert(value);
});
export const recordTaskRun = spacetimedb.reducer({ workloadId: t.string(), actualEnergyKwh: t.f64(), actualDurationSlots: t.u32(), completedSlot: t.u32(), success: t.bool(), recordedAt: t.string() }, (ctx, value) => {
  ctx.db.taskRun.insert({ id: 0n, ...value });
});
