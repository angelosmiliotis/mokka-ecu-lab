# Sensor registry

## v0.2.2 RAW-only evidence

Existing numeric definitions and validation remain unchanged. Separate opt-in 017A/0188 RAW-only monitoring creates no numeric sensor rows; complete framing does not validate an alternative format. Shape metadata records documented length/edition/table independently from observed length and missing alternative revision/source. NOx 0183 keeps individual supported-field gating. Warning-mode engine time in 0185 is a counter; static/nonzero values alone are not a current SCR-state indicator. See [layout/source boundaries](research/v0.2.2-layout-verification.md).

## v0.2 standard diesel fields

The original JSON registry and ten-sensor dashboard remain intact. Twelve code-owned definitions in `mokka_ecu_lab/sensors/diesel.py` cover PIDs 73, 78, 79, 7A, 7B, 7C, 7F, 83, 85, 86, 88 and 8B. Discovery detail/export includes every field's layout, formula, units, support flag, validity, source table, edition and verification, plus source ECU and payload. Numeric outputs carry STANDARD_DOCUMENTED and vehicle UNVERIFIED. Unsupported fields produce null, not zero; malformed layouts produce no invented readings. History field identifiers are stable ASCII keys. OEM entries have no numeric decoder and cannot authorize transmission. See [research](research/v0.2-discovery.md) for historical-layout limits.

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

Manufacturer numeric DID decoders remain future work. Standard classic-CAN multiframe reception is implemented in v0.2. Offline Research can evaluate arbitrary supplied bytes without authorizing a live command.
