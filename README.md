# ShiftOS

Grid-aware scheduling for AI data centers.

ShiftOS reduces electricity cost and peak demand by coordinating battery arbitrage with flexible AI workloads while protecting inference SLAs and emergency reserve.

## MVP

The first milestone is a 24-hour replay simulator that compares an immediate-execution baseline with an optimized schedule. Inputs include electricity prices, fixed and flexible workloads, and battery constraints. Outputs include cost, peak demand, job completion, SLA violations, and savings.

## Project layout

- `engine/` — scheduling and optimization logic
- `api/` — service API for scenarios and schedules
- `dashboard/` — operator dashboard
- `simulator/` — sample scenarios and replay tooling

## Development

Components are intentionally independent during the hackathon. See each directory for local setup instructions as they are added.

