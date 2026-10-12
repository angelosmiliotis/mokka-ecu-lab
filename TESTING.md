# Testing and vehicle validation

Run `.\.venv\Scripts\python.exe -m pytest -q` from the project root. Tests cover all ten standard formulas, conversions/validity, allowlist/injection rejection, support bitmaps including unknown pages, separate ECU provenance, 11/29-bit CAN and legacy/echo/whitespace/DLC reply formats, truncated/malformed data, serial prompt/timeout preservation, thread ownership, queued Stop and receive cancellation/rate cap, all simulation scenarios, recording/redaction/CSV/JSONL, interrupted final journal, worker Stop/reconnect/replay, manual COM entry and native Qt widget/chart startup. The serial boundary is tested with a fake serial object; it is not physical Bluetooth validation.

`scripts/generate_demo.py` runs the real simulator acquisition worker, begins recording before initialization, acquires a complete sensor cycle, stops/closes the session, exports CSV/JSONL and checks the streaming replay count against SQLite. Samples are explicitly synthetic.

`scripts/verify_ui.py` starts the native Windows Qt window in Simulation, asserts ten readings and captures `samples/dashboard.png` and `samples/raw-data.png`. `--smoke-test` exercises GUI startup/record/stop/shutdown using simulation only. The QApplication unit test uses Qt's offscreen backend; the separate native run checks the real window startup path.

The test/build results for this delivery are recorded in `samples/validation-results.txt` and `samples/ui-validation.json`. These files distinguish software/simulation validation from absent hardware validation.

Final delivery validation: **64 tests passed**. Native Windows GUI acquired ten synthetic sensors with zero acquisition errors. The demonstration recorded 37 transactions and exported 22 readings; its one cancellation record reflects Stop being pressed and is preserved intentionally. CSV has explicit SIMULATED source labels. The corrected executable in `release/validated/MokkaECULab/MokkaECULab.exe` completed its smoke test with exit code 0, 11 simulated transactions/readings, no errors, and a closed session. See `samples/executable-validation.json`. The spec excludes an incompatible Poppler ICU accidentally found in the builder's PATH and uses Windows 11's system ICU; this fixes the diagnosed packaged Qt startup error.

## Stationary hardware checklist — all pending

1. Close competing OBD clients, pair `OBDLink MX+ 36627`, verify Windows outgoing COM4 and physical adapter power. Do not use incoming COM3 by default.
2. With the vehicle safely parked and ignition in the documented diagnostic position, start recording before Connect. Choose Bluetooth serial, COM4, 115200. Confirm ATI/STI identity, accepted benign settings and retained original initialization replies. If opening fails, verify pairing/port and explicitly retry; do not automate retries.
3. Confirm adapter status separately from ECU status, protocol description, and 0100/0120/0140 support. Note every responding ECU header; compare each independently. Unsupported oil/ambient/etc. must display Not supported.
4. Begin with RPM/coolant/load at idle. Compare controlled simultaneous or closely timed observations to OBDwiz (separate clients cannot own the same COM port at once). The previously observed ~780 RPM, 54 °C and 30% are context, not acceptance constants.
5. Check every sensor under known conditions and base units. Treat MAP as absolute pressure. Document source ECU, payload, formula, timestamps, comparison instrument, ambient conditions and discrepancies.
6. Verify Start/Stop Recording, raw bytes, CSV, redacted JSONL, replay and source selection. Press Stop during polling and confirm no new sends; Disconnect must release COM4 for OBDwiz. Test unplug/ignition-off safely and verify bounded timeout and explicit reconnect.
7. Only after stationary checks, record a long controlled session and inspect request timing, error counts, memory and disk behavior. A passenger should operate diagnostics; the driver should not interact with the app.
8. Do not enable manufacturer reads until request semantics, evidence and user confirmation are obtained. Confirm decoder meaning against independent measurements before assigning VEHICLE_VERIFIED. No regeneration/SCR/adaptation routines are authorized.

## Remaining validation limits

No physical MX+, ECU, Bluetooth SPP, vehicle protocol, sensor accuracy, ignition state handling or long-drive reliability was tested. Synthetic failures approximate framing/errors; Windows Bluetooth drivers can fail differently. Multiframe ISO-TP, automatic raw/SQLite reconciliation, full Greek localization, iOS, CarPlay and manufacturer live queries are absent. Research reference comparison is positional, not automatic clock alignment. No uncertain regeneration signal triggers a warning.
