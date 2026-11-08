// Fictional observations for the public, interactive Anytime workspace.
const record = (time, kind, equipment, area, note, state = "recorded") => ({ time, kind, equipment, area, note, state });
const worker = (id, name, role, area, focus, events) => ({ id, name, role, area, focus, events });

const oilWorkers = [
  worker("O01", "Maya Chen", "Shift supervisor", "Central deck", "Pump B", [
    record("07:08", "handoff", "Pump B", "Pump bay", "Accepted morning handoff noting a small fluid trace near the lower coupling.", "watch"),
    record("08:21", "inspection", "Pump B", "Pump bay", "Compared the coupling area with the previous shift image; the trace appears wider.", "watch"),
    record("10:06", "change", "Pump B", "Pump bay", "Observed a technician adjust the lower coupling. Completion was not confirmed on camera.", "watch"),
    record("12:18", "issue", "Pump B", "Pump bay", "Fluid remained visible after the observed adjustment; requested an authorized inspection.", "open"),
    record("15:34", "handoff", "Pump B", "Control room", "Added the persistent trace and pending inspection to the next shift handoff.", "open"),
    record("18:03", "inspection", "Pump B", "Pump bay", "Last visual check still showed residue beneath the lower coupling.", "open")
  ]),
  worker("O02", "Luis Ortega", "Mechanical technician", "Pump bay", "Torque wrench", [
    record("07:24", "tool", "Torque wrench", "Tool bench 2", "Torque wrench was visible beside the blue tool case.", "recorded"),
    record("08:42", "tool", "Torque wrench", "Pump bay", "Carried the torque wrench from Tool bench 2 toward Pump B.", "recorded"),
    record("09:54", "inspection", "Pump B", "Pump bay", "Looked at the lower coupling and surrounding seal without opening the assembly.", "watch"),
    record("10:04", "change", "Pump B", "Pump bay", "Adjusted the visible coupling. The footage does not establish that the leak was repaired.", "watch"),
    record("10:31", "tool", "Torque wrench", "Locker 4", "Set the torque wrench on the middle shelf of Locker 4.", "recorded"),
    record("14:12", "handoff", "Pump B", "Maintenance desk", "Reported that the coupling was adjusted and asked for a follow-up leak check.", "open")
  ]),
  worker("O03", "Priya Nair", "Instrumentation engineer", "Control room", "Pressure gauge PG-12", [
    record("07:36", "inspection", "Pressure gauge PG-12", "Pump bay", "Recorded a 62 psi reading at Pump B inlet gauge PG-12.", "recorded"),
    record("09:10", "inspection", "Pressure gauge PG-12", "Pump bay", "Recorded 58 psi on the same gauge; the reading was below the morning observation.", "watch"),
    record("11:22", "inspection", "Valve V14", "North manifold", "Valve V14 indicator appeared between marked positions; requested confirmation from field operations.", "watch"),
    record("13:06", "inspection", "Pressure gauge PG-12", "Pump bay", "Recorded 59 psi after the coupling adjustment; pressure had not returned to the first reading.", "watch"),
    record("15:47", "change", "Sensor S8", "Control room", "Replaced a loose label on Sensor S8 without changing its wiring or calibration.", "recorded"),
    record("17:20", "handoff", "Pressure gauge PG-12", "Control room", "Passed the 62, 58, and 59 psi observations to the next instrumentation shift.", "watch")
  ]),
  worker("O04", "Jonah Brooks", "Field mechanic", "North manifold", "Valve V14", [
    record("07:52", "inspection", "Valve V14", "North manifold", "Checked the visible position marker and photographed the valve handle.", "recorded"),
    record("09:27", "issue", "Valve V14", "North manifold", "Handle marker no longer aligned with the morning photo; no work order explained the change.", "open"),
    record("11:43", "tool", "Adjustable wrench", "North manifold", "Adjustable wrench was visible on the shelf behind Valve V14.", "recorded"),
    record("12:29", "inspection", "Valve V14", "North manifold", "Confirmed the handle position visually with the control room before further work.", "watch"),
    record("14:56", "tool", "Adjustable wrench", "Tool bench 2", "Returned the adjustable wrench to the right side of Tool bench 2.", "recorded"),
    record("17:05", "handoff", "Valve V14", "North manifold", "Flagged the unexplained position change for the next field mechanic.", "open")
  ]),
  worker("O05", "Amara Okafor", "Safety lead", "South access", "Gas detector GD-3", [
    record("07:17", "inspection", "Gas detector GD-3", "South access", "Verified detector GD-3 showed a normal indicator during the opening walk-through.", "recorded"),
    record("09:38", "inspection", "Gas detector GD-3", "Pump bay", "Brought GD-3 to the Pump B area before the coupling inspection.", "recorded"),
    record("10:13", "issue", "Pump B", "Pump bay", "Asked the team to keep the area clear while the fluid source remained unconfirmed.", "open"),
    record("12:44", "inspection", "Gas detector GD-3", "South access", "Detector indicator was still normal when returned to its charging station.", "recorded"),
    record("15:08", "tool", "Gas detector GD-3", "Safety cabinet", "Placed GD-3 in the upper charging slot of the safety cabinet.", "recorded"),
    record("18:11", "handoff", "Pump B", "Control room", "Noted that the visible fluid trace still required a formal inspection.", "open")
  ]),
  worker("O06", "Theo Ramirez", "Electrical technician", "Generator room", "Generator G2", [
    record("07:48", "inspection", "Generator G2", "Generator room", "Opening walk-through showed the G2 status panel without an active fault light.", "recorded"),
    record("09:02", "issue", "Generator G2", "Generator room", "Noted a new vibration sound near the right enclosure during a routine pass.", "watch"),
    record("10:49", "inspection", "Generator G2", "Generator room", "Recorded the panel reading and a short video of the vibration for review.", "watch"),
    record("13:18", "tool", "Thermal camera", "Generator room", "Thermal camera was last visible on the cart by the G2 door.", "recorded"),
    record("15:26", "inspection", "Generator G2", "Generator room", "No fault light appeared, but the vibration sound remained audible.", "watch"),
    record("17:42", "handoff", "Generator G2", "Control room", "Shared the vibration clip and asked the next shift to compare it before service.", "watch")
  ]),
  worker("O07", "Elena Park", "Process operator", "Separator deck", "Separator S1", [
    record("07:31", "inspection", "Separator S1", "Separator deck", "Checked the separator sight glass and photographed its morning level.", "recorded"),
    record("09:46", "inspection", "Separator S1", "Separator deck", "Sight glass level appeared slightly higher than in the opening image.", "watch"),
    record("11:17", "change", "Drain valve D7", "Separator deck", "Observed a short drain operation at valve D7; the action was logged for the control room.", "recorded"),
    record("13:37", "inspection", "Separator S1", "Separator deck", "Level appeared close to the morning image after the drain operation.", "recorded"),
    record("16:14", "tool", "Sample bottle", "Sample station", "Left the sealed sample bottle in the marked tray at Sample station.", "recorded"),
    record("18:22", "handoff", "Separator S1", "Control room", "Recorded the level change and drain observation for the evening operator.", "recorded")
  ]),
  worker("O08", "Noah Williams", "Field operator", "Tank farm", "Tank T3", [
    record("07:58", "inspection", "Tank T3", "Tank farm", "Tank T3 external indicator was within the marked band on the first pass.", "recorded"),
    record("09:34", "tool", "Inspection flashlight", "Tank farm", "Inspection flashlight was visible on the T3 walkway rail.", "recorded"),
    record("11:08", "inspection", "Tank T3", "Tank farm", "No visible change at the indicator or nearby line connection.", "recorded"),
    record("13:41", "issue", "Tank T3", "Tank farm", "Found a loose identification tag on the west access ladder.", "watch"),
    record("15:53", "change", "Tank T3", "Tank farm", "Secured the identification tag and photographed its new position.", "resolved"),
    record("17:37", "tool", "Inspection flashlight", "Locker 2", "Returned the flashlight to Locker 2 after the final pass.", "recorded")
  ]),
  worker("O09", "Sara Patel", "Inspection engineer", "East line", "Line L8", [
    record("07:41", "inspection", "Line L8", "East line", "Photographed the marked corrosion patch before cleaning or measurement.", "recorded"),
    record("09:56", "inspection", "Line L8", "East line", "Compared the patch boundary with the prior reference image; no clear expansion was visible.", "recorded"),
    record("11:39", "tool", "Ultrasonic gauge", "East line", "Ultrasonic gauge case was opened at the L8 inspection point.", "recorded"),
    record("13:52", "inspection", "Line L8", "East line", "Measurement sheet was placed with the L8 work order for supervisor review.", "watch"),
    record("16:03", "tool", "Ultrasonic gauge", "Inspection cabinet", "Gauge and probe were returned to the inspection cabinet.", "recorded"),
    record("18:07", "handoff", "Line L8", "Control room", "Shared images and measurement sheet; final disposition remained with the supervisor.", "watch")
  ]),
  worker("O10", "Idris Hassan", "Relief operator", "Control room", "Shift handoff", [
    record("08:05", "handoff", "Shift handoff", "Control room", "Reviewed overnight notes on Pump B, Generator G2, and Valve V14.", "recorded"),
    record("10:24", "inspection", "Pump B", "Pump bay", "Captured a second view of the lower coupling after the mechanic's adjustment.", "watch"),
    record("12:26", "issue", "Pump B", "Pump bay", "Fluid was visible in the new frame at the same lower coupling.", "open"),
    record("14:33", "inspection", "Valve V14", "North manifold", "Valve handle remained in the position recorded at midday.", "watch"),
    record("16:49", "handoff", "Shift handoff", "Control room", "Collected the unresolved Pump B and V14 observations into the evening handoff.", "open"),
    record("18:46", "handoff", "Shift handoff", "Control room", "Evening team acknowledged the records and links to the source frames.", "recorded")
  ])
];

const dataWorkers = [
  worker("D01", "Avery Morgan", "Operations lead", "Operations room", "Rack D12", [
    record("07:06", "handoff", "Rack D12", "Operations room", "Accepted handoff noting a rising inlet temperature at Rack D12 overnight.", "watch"),
    record("08:34", "inspection", "Rack D12", "Row D", "Reviewed the inlet temperature trend and requested a floor check.", "watch"),
    record("10:41", "issue", "Rack D12", "Row D", "Asked facilities and hardware teams to compare airflow and fan status before changes.", "open"),
    record("13:22", "inspection", "Rack D12", "Operations room", "Inlet temperature began falling after the fan tray swap and aisle clearance.", "watch"),
    record("16:10", "handoff", "Rack D12", "Operations room", "Logged the sequence of findings and the remaining monitoring window.", "watch"),
    record("18:12", "handoff", "Rack D12", "Operations room", "Passed D12 trend, replacement time, and evidence links to the night team.", "recorded")
  ]),
  worker("D02", "Nina Patel", "Hardware technician", "Row D", "Rack D12", [
    record("07:29", "inspection", "Rack D12", "Row D", "Noted a warmer inlet display than neighboring Rack D11.", "watch"),
    record("09:13", "inspection", "Rack D12", "Row D", "Rear fan tray indicator showed a warning light in the camera frame.", "open"),
    record("10:12", "tool", "Fan tray puller", "Tool cage", "Checked out the fan tray puller from the tool cage.", "recorded"),
    record("11:48", "change", "Rack D12", "Row D", "Replaced the rear fan tray under the approved work order.", "resolved"),
    record("12:03", "inspection", "Rack D12", "Row D", "Replacement tray showed a normal indicator after installation.", "recorded"),
    record("15:02", "tool", "Fan tray puller", "Tool cage", "Returned the fan tray puller to its marked hook in the tool cage.", "recorded")
  ]),
  worker("D03", "Omar Reyes", "Facilities engineer", "Cooling plant", "CRAC 4", [
    record("07:44", "inspection", "CRAC 4", "Cooling plant", "Recorded CRAC 4 return air at 27.1 C during the morning check.", "watch"),
    record("09:31", "inspection", "Row D", "Row D", "Found a temporary box partially blocking the cold aisle opening.", "watch"),
    record("10:27", "change", "Row D", "Row D", "Moved the box out of the cold aisle and photographed the clear path.", "resolved"),
    record("12:51", "inspection", "CRAC 4", "Cooling plant", "Return air read 25.8 C after aisle clearance; trend continued downward.", "recorded"),
    record("15:19", "inspection", "CRAC 4", "Cooling plant", "Filter indicator remained within its marked range.", "recorded"),
    record("17:53", "handoff", "CRAC 4", "Operations room", "Shared cooling readings and the cold aisle obstruction record with operations.", "recorded")
  ]),
  worker("D04", "Leah Kim", "Power systems engineer", "Power room", "UPS B", [
    record("07:37", "inspection", "UPS B", "Power room", "UPS B panel showed battery string 2 in a watch state.", "watch"),
    record("09:24", "inspection", "UPS B", "Power room", "Compared panel view with the overnight log; no new alarm appeared.", "watch"),
    record("11:32", "issue", "UPS B", "Power room", "Battery string 2 remained in watch state; a follow-up test was scheduled.", "open"),
    record("13:58", "tool", "Insulated meter", "Power room", "Meter was visible on the cart beside UPS B.", "recorded"),
    record("15:44", "inspection", "UPS B", "Power room", "Panel status had not changed before handoff.", "watch"),
    record("18:04", "handoff", "UPS B", "Power room", "Passed the watch state and planned test to the next power engineer.", "open")
  ]),
  worker("D05", "Marcus Bell", "Network engineer", "Row C", "Switch SW-07", [
    record("07:51", "inspection", "Switch SW-07", "Row C", "Checked port indicators after an overnight packet loss report.", "watch"),
    record("09:45", "issue", "Switch SW-07", "Row C", "Port 18 showed intermittent activity while the connected host was stable.", "open"),
    record("11:06", "tool", "Fiber tester", "Network cabinet", "Fiber tester was removed from the network cabinet for the SW-07 check.", "recorded"),
    record("12:47", "inspection", "Switch SW-07", "Row C", "Fiber test notes were attached to the work order; no cable swap occurred.", "watch"),
    record("15:28", "tool", "Fiber tester", "Network cabinet", "Returned the tester to the upper shelf of the network cabinet.", "recorded"),
    record("17:41", "handoff", "Switch SW-07", "Operations room", "Asked night network staff to watch port 18 error counters.", "open")
  ]),
  worker("D06", "Sofia Alvarez", "Security and access", "Entry zone", "Door E2", [
    record("07:12", "inspection", "Door E2", "Entry zone", "Door E2 access reader showed a normal status light at shift start.", "recorded"),
    record("09:58", "inspection", "Row D", "Row D", "Verified the fan tray work area was within the approved maintenance window.", "recorded"),
    record("11:15", "change", "Door E2", "Entry zone", "Updated the maintenance access log for the D12 hardware visit.", "recorded"),
    record("13:39", "issue", "Door E2", "Entry zone", "Observed the door remain open after a delivery; requested it be secured.", "watch"),
    record("14:07", "inspection", "Door E2", "Entry zone", "Door E2 was closed and reader status returned to normal.", "resolved"),
    record("17:17", "handoff", "Entry zone", "Entry zone", "No open access issues remained at the final walkthrough.", "recorded")
  ]),
  worker("D07", "Ethan Brooks", "Storage engineer", "Row B", "Storage node B04", [
    record("07:56", "inspection", "Storage node B04", "Row B", "Node B04 status display showed a drive warning before replacement.", "watch"),
    record("09:36", "tool", "Drive caddy", "Parts room", "Collected a labeled drive caddy from shelf 3 in the parts room.", "recorded"),
    record("11:24", "change", "Storage node B04", "Row B", "Replaced the indicated drive under the approved maintenance ticket.", "resolved"),
    record("12:21", "inspection", "Storage node B04", "Row B", "New drive showed an active rebuild indicator.", "watch"),
    record("15:11", "inspection", "Storage node B04", "Operations room", "Rebuild progress advanced; the node remained under monitoring.", "watch"),
    record("18:24", "handoff", "Storage node B04", "Operations room", "Shared drive replacement time and rebuild status with the night team.", "watch")
  ]),
  worker("D08", "Chloe Nguyen", "Cooling technician", "Row D", "Rack D12 airflow", [
    record("07:32", "inspection", "Rack D12", "Row D", "Cold aisle airflow felt weaker near D12 than at D11.", "watch"),
    record("09:29", "issue", "Row D", "Row D", "Photographed the box partly covering the floor tile opening near D12.", "open"),
    record("10:35", "inspection", "Row D", "Row D", "Floor tile opening was clear after the box was moved.", "resolved"),
    record("12:34", "inspection", "Rack D12", "Row D", "Inlet display had fallen from 31.2 C to 28.7 C after cooling and fan work.", "watch"),
    record("15:38", "tool", "Airflow meter", "Facilities cabinet", "Returned the airflow meter to the facilities cabinet.", "recorded"),
    record("17:22", "handoff", "Rack D12", "Operations room", "Requested one additional D12 inlet reading during the night shift.", "watch")
  ]),
  worker("D09", "Ravi Shah", "Electrical technician", "Power room", "PDU A3", [
    record("07:43", "inspection", "PDU A3", "Power room", "PDU A3 load display was within its marked operating band.", "recorded"),
    record("09:21", "inspection", "PDU A3", "Row A", "Checked the cabinet label and outlet mapping for an upcoming work order.", "recorded"),
    record("11:58", "issue", "PDU A3", "Row A", "One outlet label did not match the current mapping sheet.", "open"),
    record("13:11", "change", "PDU A3", "Row A", "Corrected the outlet label after confirming the mapping with operations.", "resolved"),
    record("15:56", "inspection", "PDU A3", "Power room", "Load display remained in the morning range after the labeling work.", "recorded"),
    record("18:01", "handoff", "PDU A3", "Operations room", "Updated the mapping sheet and linked the corrected label image.", "recorded")
  ]),
  worker("D10", "Iris Chen", "Night shift lead", "Operations room", "Shift handoff", [
    record("08:14", "handoff", "Shift handoff", "Operations room", "Reviewed open D12, UPS B, SW-07, and B04 records from the previous shift.", "recorded"),
    record("10:52", "inspection", "Rack D12", "Row D", "Captured the D12 inlet display before fan tray replacement.", "watch"),
    record("13:04", "inspection", "Rack D12", "Row D", "Captured the inlet display again after the fan tray replacement.", "watch"),
    record("15:31", "handoff", "UPS B", "Operations room", "Added the pending battery string follow-up to the night checklist.", "open"),
    record("17:08", "handoff", "Switch SW-07", "Operations room", "Added port 18 error monitoring to the network handoff.", "open"),
    record("18:38", "handoff", "Shift handoff", "Operations room", "Night team acknowledged the D12, UPS B, SW-07, and B04 evidence links.", "recorded")
  ])
];

function buildScenario(id, title, subtitle, workers, prompts) {
  const observations = [];
  const routineTimes = ["08:02", "10:53", "14:09", "16:35"];
  workers.forEach((person, index) => {
    person.events.forEach((event, eventIndex) => observations.push({
      ...event, id: `${id === "oil" ? "OR" : "DC"}-${String(index * 10 + eventIndex + 1).padStart(3, "0")}`,
      workerId: person.id, worker: person.name, camera: `CAM-${person.id}`,
      date: "2026-11-08", source: `Camera ${person.id} · ${event.time}`
    }));
    routineTimes.forEach((time, routineIndex) => observations.push({
      ...record(time, "routine", person.area, person.area,
        `Visual walkthrough documented general conditions in ${person.area}. ${routineIndex === 0 ? "Baseline frame captured for comparison." : routineIndex === 3 ? "End-of-shift frame added to the handoff record." : "Frame kept for comparison with the prior pass."}`),
      id: `${id === "oil" ? "OR" : "DC"}-${String(index * 10 + routineIndex + 7).padStart(3, "0")}`,
      workerId: person.id, worker: person.name, camera: `CAM-${person.id}`,
      date: "2026-11-08", source: `Camera ${person.id} · ${time}`
    }));
  });
  observations.sort((a, b) => b.time.localeCompare(a.time) || a.id.localeCompare(b.id));
  return { id, title, subtitle, workers: workers.map(({events, ...person}) => person), observations, prompts };
}

const ANYTIME_SEED = {
  oil: buildScenario("oil", "Oil rig", "Maintenance, tools, safety and shift handoffs across a working rig.", oilWorkers, [
    "Why is Pump B still leaking?", "Where is the torque wrench?", "What changed at Valve V14?", "What does the next shift need to know?"
  ]),
  datacenter: buildScenario("datacenter", "Data center", "Thermal, power, network and hardware observations across a data center.", dataWorkers, [
    "Why was Rack D12 warm?", "Who worked on UPS B?", "Where is the fan tray puller?", "What is unresolved at handoff?"
  ])
};
if (typeof window !== "undefined") window.ANYTIME_SEED = ANYTIME_SEED;
if (typeof module !== "undefined") module.exports = ANYTIME_SEED;
