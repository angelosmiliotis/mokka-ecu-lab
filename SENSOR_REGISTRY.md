# Sensor registry

`mokka_ecu_lab/sensors/standard.json` holds structured definitions. Runtime schema validation requires ID, name, hexadecimal PID, service, positive response, source ECU, layout/length, byte order, signedness, scale/offset, range, formula, unit, validity, limitations, evidence and verification. Duplicate IDs/PIDs and malformed metadata are rejected.

| PID | Sensor | Formula | Original unit |
|---|---|---|---|
| 0C | Engine RPM | (256 A + B) / 4 | rpm |
| 05 | Coolant temperature | A − 40 | °C |
| 0D | Vehicle speed | A | km/h |
| 04 | Calculated engine load | 100 A / 255 | % |
| 0B | Manifold absolute pressure | A | kPa absolute |
| 0F | Intake air temperature | A − 40 | °C |
| 10 | Mass air flow | (256 A + B) / 100 | g/s |
| 42 | Control module voltage | (256 A + B) / 1000 | V |
| 46 | Ambient air temperature | A − 40 | °C |
| 5C | Engine oil temperature | A − 40 | °C |

A/B are unsigned payload bytes after `41 PID`. Responses have one or two relevant sensor bytes; CAN padding is not part of the calculation. PID support bitmaps have exactly four data bytes. MAP is absolute pressure and is not a turbo gauge pressure estimate. Altitude/barometric pressure would be required for a justified gauge conversion.

Formula sources were cross-checked against the original [python-OBD command definitions](https://github.com/brendan-w/python-OBD/blob/master/obd/commands.py), [decoder source](https://github.com/brendan-w/python-OBD/blob/master/obd/decoders.py) and [unit/scaling source](https://github.com/brendan-w/python-OBD/blob/master/obd/UnitsAndScaling.py). SAE J1979/J1979-DA is the governing standard; a paid current SAE annex was not acquired. Source references are also embedded in the definitions. Vehicle accuracy and support remain unverified.

## Verification and presentation

- `STANDARD_VERIFIED`: standardized formula cross-check and test coverage; not a claim of this vehicle's support or calibration.
- `VEHICLE_VERIFIED`: reserved for independent vehicle evidence. No current sensor is assigned this state.
- `EXPERIMENTAL`: hypothesis, never implicitly promoted because values look plausible.
- `UNSUPPORTED`: support bitmap for the selected ECU does not advertise the PID.
- `INVALID`: malformed/truncated data or failed validity check.

UI also distinguishes unavailable/no sample and stale/last valid sample. Unsupported values are never fabricated as zero. Base units are stored even when alternate display units are selected. Per-sensor observed update rate appears on the dashboard; nominal rate is selected-supported-sensor round-robin within the aggregate cap.

## Extension

Add a validated Mode 01 definition with an honest verification state and evidence. The GUI reads registry metadata and needs no sensor-specific widget changes. The generic decoder currently supports one/two-byte, big-endian, unsigned linear scaling. Specialized future layouts should add a named decoder implementation with tests. New live PIDs remain blocked until the code-owned policy is reviewed and deliberately updated. Editing registry metadata is an explicit source modification, not evidence of physical verification; never relabel a speculative formula to make it appear verified.

Manufacturer DID registries and multiframe responses are future work. Offline Research can evaluate arbitrary supplied bytes now without authorizing a live command.
