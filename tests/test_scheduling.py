from collections import Counter
import pytest
from mokka_ecu_lab.adapter.scheduling import PollScheduler, nominal_interval
from mokka_ecu_lab.protocols import LIVE_PIDS, BITMAP_PIDS, ADAPTER_COMMANDS, validate_command, UnsafeRequest


def test_default_is_round_robin_and_priority_does_not_starve():
    scheduler = PollScheduler()
    assert [scheduler.next([12, 5, 4]) for _ in range(6)] == [12, 5, 4, 12, 5, 4]
    sequence = [scheduler.next([12, 5, 4], {12: 3, 5: 2}) for _ in range(60)]
    assert Counter(sequence) == {12: 30, 5: 20, 4: 10}
    assert all(4 in sequence[i:i+6] for i in range(len(sequence)-5))
    assert nominal_interval(12, {12: 3, 5: 2, 4: 1}, 4) == .5
    assert nominal_interval(4, {12: 3, 5: 2, 4: 1}, 4) == 1.5


def test_schedule_changes_drop_unselected_pids_and_bound_weights():
    scheduler = PollScheduler()
    scheduler.next([12, 5], {12: 4})
    assert {scheduler.next([5]) for _ in range(12)} == {5}
    assert scheduler.next([]) is None
    sequence = [scheduler.next([12, 12, 5, 0x22, 0x00], {12: 100, 5: 0, 0x22: 999}) for _ in range(10)]
    assert Counter(sequence) == {12: 8, 5: 2}


def test_read_only_policy_is_unchanged_by_scheduler():
    assert LIVE_PIDS == {4, 5, 11, 12, 13, 15, 16, 66, 70, 92}
    assert BITMAP_PIDS == set(range(0,256,32))
    assert ADAPTER_COMMANDS == {"ATI", "STI", "ATE0", "ATL0", "ATS1", "ATH1", "ATM0", "ATTP0", "ATST64", "ATDP", "ATDPN"}
    for command in ("04", "0902", "22F190", "2701", "2E1234", "3101FF00", "ATSH7E0", "0122"):
        with pytest.raises(UnsafeRequest): validate_command(command, set(range(256)))
