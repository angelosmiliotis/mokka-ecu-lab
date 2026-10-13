"""Derived UI descriptions only. No transport, scheduler or decoder ownership."""
from enum import StrEnum


class StepState(StrEnum):
    COMPLETED = 'COMPLETED'
    CURRENT = 'CURRENT'
    AVAILABLE = 'AVAILABLE'
    BLOCKED = 'BLOCKED'
    NOT_STARTED = 'NOT_STARTED'
    IN_PROGRESS = 'IN_PROGRESS'


STEP_LABELS = {
    StepState.COMPLETED: 'Done', StepState.CURRENT: 'Next action',
    StepState.AVAILABLE: 'Available', StepState.BLOCKED: 'Needs setup',
    StepState.NOT_STARTED: 'Not started', StepState.IN_PROGRESS: 'In progress',
}

HUMAN_NAMES = {0x7A: 'DPF pressure', 0x7C: 'DPF temperature',
               0x78: 'Exhaust temperature', 0x83: 'NOx sensor',
               0x85: 'AdBlue tank level', 0x88: 'SCR inducement status',
               0x8B: 'DPF regeneration status'}


def source_description(mode, *, live_selected=False):
    if mode == 'REPLAY': return 'REPLAY — recorded evidence, offline'
    if mode == 'SIMULATED': return 'SIMULATION — synthetic data'
    if mode.startswith('LIVE'): return 'LIVE — Bluetooth / Serial ECU'
    return 'LIVE — Bluetooth / Serial ECU' if live_selected else 'SIMULATION — synthetic data'


def measurement_status(*, now, sent_at, replay, active, scheduled, valid,
                       same_context, expected=0, intervals=()):
    """One freshness calculation for cards, Dashboard and Drive Capture.

    Recent timestamps alone never establish current acquisition. Observed
    intervals supplement the existing nominal schedule; neither changes it.
    """
    age = now - sent_at if sent_at is not None and not replay else None
    mean = sum(intervals) / len(intervals) if intervals else 0
    threshold = max(5., expected * 2.5, mean * 2.5)
    current = bool(not replay and active and scheduled and valid and same_context
                   and age is not None and 0 <= age <= threshold)
    return dict(current=current, replay=replay, age=age, threshold=threshold,
                label='Recorded (offline)' if replay else 'Current sample' if current
                else 'Last recorded value · Stale')
