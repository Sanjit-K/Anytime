# Hardware demonstration

`HardwareController` runs a real, bounded SHA-256 computation on the Arduino
UNO Q's Linux processor using USB/ADB. It does not flash firmware. A uniquely
named worker is copied to `/tmp`, run as the board's current ADB user, then removed.
The worker uses one CPU thread at a maximum 35% duty cycle by default; runs are
limited to 1–300 active seconds and a 15-minute wall-clock maximum.

```python
from hardware import HardwareController

hardware = HardwareController()
print(hardware.snapshot())
hardware.start(duration_seconds=60)  # Arduino required; no silent fallback
hardware.pause()
hardware.resume()
hardware.stop()
```

Explicit `start(target="mac")` runs real compute on the Mac instead and labels
the target accordingly. `target="auto"` and `target="arduino"` both require an
accessible Arduino Linux board with Python 3. If the device is disconnected or
unauthorized, its status is unavailable and the start request fails clearly.

The runnable worker can also be copied manually to the board:

```sh
python3 -u hardware/worker.py --duration 60
```

Send JSON lines `{"action":"pause"}`, `{"action":"resume"}`, or
`{"action":"stop"}` to its standard input. EOF stops it. It reports JSON
telemetry twice per second. The job's progress is elapsed active job time divided
by requested duration; its throughput is measured hashes per active second.
Active time includes duty-cycle rest periods but excludes pauses. CPU time is
separately measured. This is a compute demonstration, not LLM inference.

Mac battery percentage and AC/battery power source are read from `pmset -g batt`.
No charging settings are changed. Battery watts and capacity are unavailable in
this interface, so those fields are null. Arduino electrical power is not
measured by this worker. Any conversion of its runtime to kWh must be shown as
an explicitly configured estimate. The energy source switching visual is a
simulation; it cannot control the Mac charger or route the Mac battery output.

Validated on the attached board: device tree model `Arduino SA,Imola`, Debian
GNU/Linux 13, Python 3. Live start, pause, resume, and stop were acknowledged by
the board with increasing hash counts. macOS reported Battery Power at test time.
