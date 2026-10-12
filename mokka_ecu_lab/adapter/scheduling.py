"""Optional weighted scheduling; the transport remains the rate/policy boundary."""
from mokka_ecu_lab.protocols import LIVE_PIDS


def priority_weights(pids, priorities=None):
    # Never let scheduling admit new requests, duplicates or an unbounded weight.
    priorities = priorities or {}
    return {pid: max(1, min(4, int(priorities.get(pid, 1))))
            for pid in dict.fromkeys(pids) if pid in LIVE_PIDS}


def nominal_interval(pid, weights, rate):
    return sum(weights.values()) / (weights[pid] * max(.25, min(4., rate)))


class PollScheduler:
    """Smooth weighted round-robin with bounded, non-starving priorities 1–4."""
    def __init__(self):
        self.weights = {}
        self.scores = {}

    def next(self, pids, priorities=None):
        weights = priority_weights(pids, priorities)
        if weights != self.weights:
            self.weights = weights
            self.scores = dict.fromkeys(weights, 0)
        if not weights:
            return None
        for pid, weight in weights.items():
            self.scores[pid] += weight
        pid = max(weights, key=self.scores.get)
        self.scores[pid] -= sum(weights.values())
        return pid
