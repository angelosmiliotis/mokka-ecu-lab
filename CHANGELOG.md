# Changes

## 0.1.1

- Parse Mode 01 negative replies, including CAN length/DLC, headerless and legacy frames. Retain NRC/ECU/reason alongside original command and raw reply. Keep positive measurements from other responding ECUs separate.
- Explain NRC 22 as Conditions Not Correct without asserting ignition state or a vehicle fault. Three consecutive ECU failures halt polling; explicit reconnect is required and automatic retries remain absent.
- Show per-ECU stale values, source evidence, actual intervals, recent gaps and current/support coverage. Stop invalidates current coverage immediately. Replay stays offline and cannot create a new live recording; v0.1.0 negative journals are classified during replay without modification.
- Finalize recording on Disconnect/shutdown and support either Stop order. Close previous nonempty sessions on reconnect/source change instead of relabeling simulation as live data. Add Finish session and ignition-off instructions.
- Add optional priorities 1–4 using smooth weighted round-robin; preserve the existing total 4 req/s ceiling, transport ownership, cancellation and exact code-owned read-only allowlists.
- Add regression tests from minimal response strings, loss-of-conditions simulation, session lifecycle, rate cap, source separation and GUI freshness. Full user vehicle logs are excluded.

Vehicle revalidation of this patch is pending. Do not treat software or fixture tests as actual hardware validation.
