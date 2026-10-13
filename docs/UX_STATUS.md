# Mokka ECU Lab v0.2.6 — status and workflow guide

This release polishes the v0.2.5 native Windows interface. The dark theme,
sidebar, architecture and existing operations remain. No acquisition worker,
transport, allowlist, scheduler, decoder or offline evidence engine is rewritten.

## Follow actual state

Drive Capture keeps seven navigation steps. Green **Done** means a confirmed
result; amber **Next action** is a recommendation, never success. **In progress**
requires the worker's acknowledgment. **Available**, **Needs setup** and
**Not started** explain other states. Merely visiting a step sends no commands,
starts no scan and changes no recording. The dominant contextual action invokes
one existing operation only; the application never advances operations automatically.

**Record** is In progress while recording is actually active. Recording Off
never shows completed recording. You may start recording before connecting to
preserve adapter initialization. A click first shows an awaiting-confirmation
message. The worker's recording event, not the click, establishes success.

Discovery must complete for the selected ECU in the current connection before
preparing a preset. Preparation sends nothing. NOx and the fixed RAW-only
017A/0188 options remain unchecked explicit opt-ins. Start Drive Capture requires
an eligible configured selection. Monitoring can run with Recording Off; its
wording explicitly says no session is being recorded.

Finish is available for an active recording or capture. Its normal path stops
polling and closes the recording while leaving the adapter open. The previous
receive-cancel/failure safety can disconnect to restore prompt synchronization;
the UI then explains reconnect prerequisites. Resume never bypasses this safety.
No hidden disconnect/connect sequence was added.

Export requires a confirmed closed session. Completion checks the actual saved
session, and Export becomes Done only after a successful write. The exact saved
destination remains visible. A Research Bundle is private diagnostic evidence;
review it before sharing. Original journals and private reports remain local.

## Understand the measurements

Dashboard and Drive Capture use the same freshness calculation. A current
measurement needs active acquisition, current ECU/source/context, valid evidence,
an eligible scheduled PID and a recent actual sample. Existing nominal scheduling
and observed intervals inform the age threshold. Recent timestamps alone cannot
make stopped, disconnected or failed acquisition current. Future timestamps and
unknown provenance do not establish freshness.

Three facts stay separate: **Current/Stale/Recorded offline**, **Basic polling /
Discovery / Drive Capture**, and **Recording Active/Off**. Per-sample tooltips also
say whether that sample was observed while the current journal was recording.
Starting recording cannot retroactively record a previously displayed sample.
Replay preserves its recorded source and remains offline even while another
connection source is being prepared.

SIMULATION — synthetic data is visible globally and beside Dashboard/Drive
Capture, with the selected scenario. LIVE — Bluetooth / Serial ECU includes the
selected port and observed ECU when known. Adapter initialization is distinct
from a positive ECU response; neither certifies hardware/vehicle compatibility.
Changing an inactive source clears old preview measurements/support/configuration,
never the stored session files. There is no automatic connection or reuse of
historical vehicle support in a new session.

The simple capture view prioritizes essential values and understandable DPF,
AdBlue and NOx names. Technical details reveal original PID names/numbers,
weights, observed intervals/max gaps, raw evidence and omissions. Unsupported
current-scenario/ECU readings stay unavailable. Six-byte 017A is RAW evidence
with **No verified numeric decoder**, never a pressure value. Simulator 018B
support is not a statement about the real Mokka ECU.

Intentional Stop cancellations remain in the total transaction-error count and
original journal. They are excluded from the UI monitoring-failure count.

## Actual Windows screenshots — synthetic data only

| State | Screenshot |
|---|---|
| Before: v0.2.5 capture | [Before](screenshots/v0.2.5/drive-capture.png) |
| Basic polling current in Capture | [After](screenshots/v0.2.6/capture-basic-current.png) |
| Recording before connection | [Acknowledged recording](screenshots/v0.2.6/record-before-connect.png) |
| Active capture, simple view | [Capture](screenshots/v0.2.6/capture-active.png) |
| Technical view | [Details](screenshots/v0.2.6/capture-technical.png) |
| Finished, adapter remains connected | [Export is next](screenshots/v0.2.6/capture-finished.png) |
| Successful private export | [Saved destination](screenshots/v0.2.6/capture-exported.png) |
| LIVE preparation, no hardware connected | [No current ECU confirmed](screenshots/v0.2.6/live-preparation.png) |
| Dashboard | [Cards](screenshots/v0.2.6/dashboard.png) |

Validation results are recorded in [the public counts](../samples/v0.2.6-validation.json).
The final suite passed **382 tests**, zero failures, process exit 0 (137.17 s),
including 18 new workflow regressions. All 84 native major-page/size/DPI checks
passed and their screenshots were inspected. Native simulation verified recording
before connection, current basic polling in both views, explicit RAW/NOx capture,
closed-session completion and private export receipts. The workflow journal
retained one expected layout mismatch and two intentional Stop cancellations;
there were zero monitoring failures. Separate bundle validation checked all twelve
members and their checksums, unchanged original journals, six trend charts and
private HTML/JSON export.

The final executable's simulation/record/close smoke test exited 0: 11 requests,
zero errors and one closed session. Its offline analyzer exited 0, and JSON/HTML
exactly matched source output. All 30 packaged project modules match the final
compiled source. The Windows package keeps `_internal` beside the executable.

Native checks use the Windows Qt plugin, synthetic sessions and controlled Qt
pixel ratios at four laptop/desktop sizes. They do not certify actual hardware
or every Windows display setting. No private LIVE log, bundle, route history,
report, identifier or copyrighted SAE material is distributed.

Full Greek translation remains deferred; existing partial Greek labels survive.
No decorative animations, extra dependencies, networking or additional ECU
queries were introduced.
