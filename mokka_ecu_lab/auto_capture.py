"""Pure preset planning and bounded acquisition receipts; no transport access."""
from copy import deepcopy
from .capture import capture_plan
from .protocols import LIVE_PIDS, DISCOVERY_PIDS, support_state
from .layouts import RAW_ONLY_PIDS, raw_eligibility

PRESETS = ('Comprehensive / All supported sensors', 'DPF Research Priority')
ALL_SENSOR_PIDS = LIVE_PIDS | DISCOVERY_PIDS
PRIORITY = {0x7A: 4, 0x0C: 3, 0x0D: 2, 0x0B: 2, 0x10: 2, 0x05: 2}


def affirmative_bitmap(support, pages, ecu, pid):
    """Current, ordered per-ECU continuation; a bare supported set is insufficient."""
    known, recorded = support.get(ecu, set()), pages.get(ecu, set())
    base = ((pid - 1) // 32) * 32
    return pid in known and all(p in recorded and (p == 0 or p in known)
                               for p in range(0, base + 1, 32))


def auto_plan(support, pages, observations, ecu, *, prepared, consent, preset=PRESETS[0]):
    if preset not in PRESETS:
        raise ValueError('Unknown automatic preset')
    numeric, raw, omitted, matrix = [], [], [], []
    for pid in sorted(ALL_SENSOR_PIDS):
        sample = observations.get((ecu, pid), {})
        state = support_state(support.get(ecu, set()), pages.get(ecu, set()), pid)
        reason = ''
        positive = bool(not sample.get('error') and any(
            f.get('state') == 'AVAILABLE' and f.get('value') is not None
            for f in sample.get('fields', [])))
        representation = 'UNAVAILABLE'
        if not prepared:
            reason = 'Completed current ECU Discovery required'
        elif not affirmative_bitmap(support, pages, ecu, pid):
            reason = 'Support ' + state.upper() + '; affirmative ordered bitmap evidence required'
        elif positive:
            numeric.append(pid); representation = 'NUMERIC'
        elif pid in RAW_ONLY_PIDS and raw_eligibility(sample):
            if consent:
                raw.append(pid); representation = 'RAW ONLY'
            else:
                reason = 'Preset RAW consent not given'
        else:
            reason = sample.get('error') or 'No strictly valid positive Discovery sample'
        if reason:
            omitted.append(dict(pid=f'{pid:02X}', reason=reason))
        matrix.append(dict(pid=f'{pid:02X}', support=state,
            bitmap_affirmative=affirmative_bitmap(support, pages, ecu, pid),
            positive_observed=bool(positive or raw_eligibility(sample)),
            layout=sample.get('layout_status', 'STANDARD_REGISTRY' if positive else 'NO_SAMPLE'),
            data_length=sample.get('data_length'), representation=representation,
            included=not bool(reason), reason=reason))
    validated = capture_plan(support, pages, observations, ecu, prepared=prepared,
                             selected=numeric, raw_selected=raw)
    weights = {p: PRIORITY.get(p, 1) if preset == PRESETS[1] else 1
               for p in validated['weights']}
    return dict(ecu=ecu, preset=preset, consent=bool(consent), weights=weights,
                raw_pids=validated['raw_pids'], omitted=omitted + validated['omitted'],
                matrix=matrix, prepared=prepared)


class AcquisitionReceipt:
    """Constant memory per PID; counts only after successful recorder append."""
    def __init__(self, preset, consent, timestamp):
        self.data = dict(schema_version=1, preset=preset, raw_consent=bool(consent),
            consent_timestamp=timestamp, consent_scope='Existing standard allowlist + eligible 017A/0188 RAW',
            state='STARTING', reason='Explicit preset action accepted', transitions=[],
            requested_plan={}, effective_schedule={}, confirmed_raw_pids=[],
            observed={}, error_categories={}, dpf=dict(state='NOT_READY', recorded_positive_six_byte_frames=0),
            acquisition_status_counts={},acquisition_error_categories={},
            hardware_verified=False)
        self._last = {}; self._interval_sums = {}; self._raw_proof = []

    def transition(self, state, reason, timestamp):
        self.data.update(state=state, reason=reason)
        # Recovering intermittent PID errors may alternate READY/PARTIAL indefinitely.
        # Keep a bounded recent workflow history; the complete transaction journal remains.
        self.data['transitions'].append(dict(state=state, reason=reason, timestamp=timestamp))
        if len(self.data['transitions'])>64:
            del self.data['transitions'][0]
            self.data['older_transition_count']=self.data.get('older_transition_count',0)+1

    def configure(self, plan, *, session_id, context_id, mode, bitmap_evidence, rate):
        self.data.update(session_id=session_id, context_id=context_id, mode=mode,
            source_kind='SIMULATED' if mode == 'SIMULATED' else 'ECU_READING', ecu=plan['ecu'],
            bitmap_evidence=deepcopy(bitmap_evidence), requested_plan=deepcopy(plan),
            proposed_schedule={f'{p:02X}':dict(weight=w, nominal_interval_seconds=sum(plan['weights'].values()) / (w * max(.25, min(4., rate))))
                                for p,w in plan['weights'].items()},
            effective_schedule={},confirmed_raw_pids=[],
            rate_limit=min(4., rate), interval_note='Estimate at selected aggregate rate; transport/disk delays may lower frequency')
        row=next((r for r in plan.get('matrix',[]) if r['pid']=='7A'),{})
        self.data['dpf'].update(bitmap_support=row.get('support','unknown').upper(),
            bitmap_provenance='ORDERED_POSITIVE_RAW_BITMAPS' if row.get('bitmap_affirmative') else 'MISSING_OR_NON_AFFIRMATIVE',
            discovery_positive_observed=row.get('positive_observed',False),
            discovery_data_length=row.get('data_length'),discovery_decoder=row.get('layout','NO_SAMPLE'))

    def acknowledge(self, weights, raw_pids, ecu, timestamp):
        plan=self.data['requested_plan']
        if weights!=plan['weights'] or set(raw_pids)!=set(plan['raw_pids']) or ecu!=plan['ecu']:
            raise ValueError('Worker schedule differs from requested preset')
        self.data['effective_schedule']=deepcopy(self.data['proposed_schedule'])
        self.data['confirmed_raw_pids']=[f'{p:02X}' for p in sorted(raw_pids)]
        self.data['worker_schedule_acknowledged_at']=timestamp

    def observe(self, record, readings, *, recorded, active):
        pid = record.get('pid')
        if not recorded or not active or pid not in self.data['effective_schedule']:
            return
        if record.get('context_id') != self.data.get('context_id') or record.get('mode') != self.data.get('mode'):
            return
        if record.get('replay') or record.get('source_kind')!=self.data.get('source_kind'): return
        ecu = self.data['ecu']
        entry = self.data['observed'].setdefault(pid, dict(sent=0, positive_samples=0,
            decoded_samples=0, raw_only_samples=0, interval_count=0, mean_interval_seconds=None,
            maximum_gap_seconds=None, minimum_gap_seconds=None, gaps_over_twice_estimate=0, failures=0))
        entry['sent'] += bool(record.get('sent'))
        entry.update(last_status=record['status'],last_error=record.get('error',''),last_query_timestamp=record['timestamp'])
        errors = record.get('protocol_errors', [])
        category = ('INTENTIONAL_CANCELLATION' if record['status'] == 'CANCELLED' else
                    'TRANSPORT_FAILURE' if record['status'] == 'TRANSPORT_ERROR' else
                    'DECODER_LAYOUT' if errors and all(e.get('category') == 'DECODER_LAYOUT' for e in errors) else
                    'ECU_OR_FRAMING' if record['status'] != 'OK' else None)
        if category:
            categories=self.data['error_categories']; categories[category]=categories.get(category,0)+1
            entry['failures'] += category != 'INTENTIONAL_CANCELLATION'
        if not record.get('sent') or not any(p.get('ecu') == ecu for p in record.get('parsed', [])):
            return
        # A positive from another ECU or a malformed reply never establishes target proof.
        if any(e.get('ecu') in {ecu, None} and e.get('category') != 'DECODER_LAYOUT' for e in errors):
            return
        entry['positive_samples'] += 1
        entry['decoded_samples'] += any(r.get('ecu') == ecu for r in readings)
        raw = next((s for s in record.get('raw_samples', [])
                    if s.get('ecu') == ecu and s.get('framing_valid') and s.get('raw_only')), None)
        entry['raw_only_samples'] += bool(raw)
        ns = record['monotonic_ns']
        previous = self._last.get(pid)
        if previous is not None and ns > previous:
            gap = (ns - previous) / 1e9
            entry['interval_count'] += 1
            self._interval_sums[pid] = self._interval_sums.get(pid, 0.) + gap
            entry['mean_interval_seconds'] = self._interval_sums[pid] / entry['interval_count']
            entry['maximum_gap_seconds'] = max(gap, entry['maximum_gap_seconds'] or 0.)
            entry['minimum_gap_seconds'] = min(gap, entry['minimum_gap_seconds'] or gap)
            entry['gaps_over_twice_estimate'] += gap > 2 * self.data['effective_schedule'][pid]['nominal_interval_seconds']
        self._last[pid] = ns
        entry.setdefault('first_timestamp', record['timestamp'])
        entry['last_timestamp'] = record['timestamp']
        entry['last_monotonic_ns'] = ns
        if pid == '7A' and raw and raw.get('data_length') == 6 and not any(p['transaction_id']==record['id'] for p in self._raw_proof):
            dpf = self.data['dpf']; dpf['recorded_positive_six_byte_frames'] += 1
            dpf.update(last_timestamp=record['timestamp'], last_payload_hex=raw['payload_hex'],
                       last_length=6, decoder='UNVERIFIED', numeric_available=False)
            if len(self._raw_proof) < 2:
                self._raw_proof.append(dict(transaction_id=record['id'], timestamp=record['timestamp'],
                                            monotonic_ns=ns, data_length=6))
            dpf['first_two_stored_frames'] = list(self._raw_proof)

    def track_transaction(self, record):
        counts=self.data['acquisition_status_counts']; status=record['status']
        counts[status]=counts.get(status,0)+1
        errors=record.get('protocol_errors',[])
        category=('INTENTIONAL_CANCELLATION' if status=='CANCELLED' else
                  'TRANSPORT_FAILURE' if status=='TRANSPORT_ERROR' else
                  'DECODER_LAYOUT' if errors and all(e.get('category')=='DECODER_LAYOUT' for e in errors) else
                  'ECU_OR_FRAMING' if status!='OK' else None)
        if category:
            totals=self.data['acquisition_error_categories']; totals[category]=totals.get(category,0)+1

    def readiness(self, active=True):
        dpf = self.data['dpf']
        scheduled = '7A' in self.data['effective_schedule'] and '7A' in self.data['confirmed_raw_pids']
        dpf['worker_scheduled'] = bool(scheduled and active)
        count = dpf['recorded_positive_six_byte_frames']
        if active and scheduled and count >= 2:
            latest=self.data['observed'].get('7A',{})
            if latest.get('last_status','OK')!='OK':
                dpf.update(state='PARTIAL',reason='Stored proof exists but latest 017A query failed: '+latest.get('last_error','Inspect transaction evidence'))
            else:
                dpf.update(state='READY', reason='Worker schedule confirmed; at least two six-byte RAW frames stored. Research evidence only.')
        elif active and scheduled:
            dpf.update(state='WAITING', reason=f'017A RAW scheduled; {count}/2 stored six-byte positive frames')
        else:
            row = next((r for r in self.data.get('requested_plan', {}).get('matrix', []) if r['pid'] == '7A'), {})
            dpf.update(state='PARTIAL', reason='Capture inactive; stored evidence retained. Polling is stopped.' if not active else row.get('reason') or
                       ('Documented numeric layout; six-byte RAW target not applicable' if row.get('representation') == 'NUMERIC' else
                        'Capture inactive or 017A RAW not eligible; other eligible sensors can continue'))
        return dpf['state']

    def snapshot(self):
        return deepcopy(self.data)
