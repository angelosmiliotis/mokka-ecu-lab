# Mokka ECU Lab v0.2.5 desktop guide

The redesign uses native PySide6 Widgets and QtCharts. Shared colors, spacing,
typography, states, table density and original line icons live in `ui/theme.py`;
the sidebar, scroll containers, wrapping action rows, sensor cards and capture
stepper live in `ui/components.py`. No fonts or third-party brand assets are bundled.

## Working with the application

- **Dashboard:** actual measurements, ECU/source and age. A dash means missing
  evidence, never zero. Stopped acquisition marks cached readings stale. Signal
  history plots acquired points only; one sample cannot establish a trend.
  All measurements, sensor selection/priorities and the activity log are separate
  subpages. Focused capture is limited to seven indications; recorded supported
  replacements are configured in Sensor selection and send no requests.
- **Connection settings:** choose Simulation or Bluetooth / Serial LIVE. Only
  relevant configuration is shown. Start Simulation / Connect is explicit;
  connecting disables configuration. Rate settings share the unchanged maximum
  four application requests/s. The panel closes after successful connection and
  can be reopened. Stop polling, Finish recording and Disconnect are distinct.
- **Drive Capture:** Connect → Record → Discover → Configure → Capture → Finish
  → Export. Step buttons show preparation or navigate; they never start those
  actions. Start recording before connecting when initialization evidence matters.
  Prepare the recommended preset only after Discovery for the same ECU. NOx and
  RAW-only remain unchecked explicit opt-ins. Configure while stationary; during
  a journey use passive display, with a passenger operating the laptop.
- **Discovery:** explicit standard-only scan and monitoring for the selected ECU,
  support/observation/layout counts, system filter and optional original-evidence
  inspection. Unsupported or unknown PIDs are never probed automatically.
- **Sessions:** date, duration, source, recorded ECU, transactions, errors and
  completion. A closed Research Bundle is a complete local evidence ZIP; CSV is
  decoded measurements; JSONL is raw transactions. Private HTML/JSON reporting
  is in Research. Export success includes the local destination.
- **Sensor Explorer:** search and category filter, formula verification separate
  from support, selected-sensor metadata and optional technical columns.
- **Raw Data:** filter ECU/PID/status/errors, inspect original text and hex
  separately from interpretation, and copy the selected original response.
  The 500-row preview does not truncate the recorded journal.
- **Research:** local catalog/provenance, source-separated analyzer and experimental
  hypotheses remain available. Compatibility supports search, filters and numeric
  sample sorting; selection retains the exact evidence after sorting. Checksum
  integrity is file integrity, never vehicle compatibility verification.
  SCR sections separate current inducement at the recorded timestamp, current
  reasons, historical flags and distances, tank level, warning time and NOx.
  Inactive inducement does not mean the SCR system is disabled. Six-byte 017A
  stays RAW ONLY with unverified numeric meaning.

## Keyboard and scaling

Alt+1…7 follows the sidebar order; Tab/Space/Enter operate controls.
Ctrl+Shift+R activates Start recording when enabled. Focus has a visible outline;
status text never depends only on color. Narrow windows use icon navigation with
accessible names/tooltips. Pages scroll vertically and controls wrap where needed;
wide evidence tables retain their own horizontal scrolling. No continuous
monitoring animations or sounds are used.

Native validation uses real Qt windows with controlled device-pixel ratios
1.00/1.25/1.50 and logical dimensions corresponding to 1280×720, 1366×768,
1536×864 and 1920×1080 physical pixels. This exercises application DPI rendering;
it does not claim to change or test every Windows system/display setting.
All screenshots below use synthetic simulator data, including any PID 018B
response shown. A simulator response does not assert support on a real Mokka.

## Actual Windows screenshots

| Page | Screenshot |
|---|---|
| Dashboard | [Measured signals](screenshots/v0.2.5/dashboard.png) |
| Drive Capture | [Active RAW/NOx capture](screenshots/v0.2.5/drive-capture.png) |
| Sessions | [Local session exports](screenshots/v0.2.5/sessions.png) |
| Sensor Explorer | [Availability and metadata](screenshots/v0.2.5/sensor-explorer.png) |
| Raw Data | [Original response inspection](screenshots/v0.2.5/raw-data.png) |
| Discovery | [Standard evidence](screenshots/v0.2.5/discovery.png) |
| Research | [Compatibility](screenshots/v0.2.5/research.png), [SCR sections](screenshots/v0.2.5/research-scr.png) |

Compare [v0.2.4 capture](screenshots/v0.2.5/before-capture.png) with
[v0.2.5 capture](screenshots/v0.2.5/drive-capture.png). Both use synthetic data.

Full Greek translation, custom gauge editors and decorative animations are
deferred. Existing partial Greek labels and all recording/replay/research
capabilities remain. The unchanged live protocol, allowlists, serialized worker,
scheduler and numeric decoders are verified by the existing regression tests.
No real hardware or physical component health is certified by UI validation.

## Release validation

364 regression tests passed, with process exit 0 (118.33 seconds). Native
simulator validation completed RAW-only 017A/0188, explicit NOx selection,
recording continuity, original-journal preservation, twelve-member bundle
checksums, source-separated research, and private HTML/JSON export. Native
page validation passed 84 major-page/size/DPI combinations; actual screenshots
were inspected and the layout was revised.

The final packaged application exited 0 after simulation, recording and close:
11 requests, zero errors and one closed session. Its headless analyzer exited
0 and JSON/HTML matched source output exactly. All 29 packaged project modules
match current compiled source. Original icons/theme are code-owned and the
Windows ZIP retains `_internal`. See [public validation counts](../samples/v0.2.5-validation.json).
No private vehicle input, bundle, raw log, route or SAE document is distributed.
