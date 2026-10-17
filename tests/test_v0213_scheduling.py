"""Constructed eligible catalog; no vehicle bitmap or recorded payload."""
from collections import Counter
from mokka_ecu_lab.auto_capture import ALL_SENSOR_PIDS,PRESETS,auto_plan,AcquisitionReceipt,CORRELATED_FAST,CORRELATED_CONTEXT
from mokka_ecu_lab.adapter.scheduling import PollScheduler
from mokka_ecu_lab.protocols import BITMAP_PIDS


def constructed_plan(profile):
    support={'7E9':set(ALL_SENSOR_PIDS)|set(BITMAP_PIDS)}
    samples={('7E9',pid):dict(fields=[dict(state='AVAILABLE',value=1)]) for pid in ALL_SENSOR_PIDS}
    return auto_plan(support,{'7E9':set(BITMAP_PIDS)},samples,'7E9',prepared=True,consent=True,preset=profile)


def test_correlated_goal_keeps_all_gates_and_balances_cadence_with_slow_status():
    balanced=constructed_plan(PRESETS[3]);legacy=constructed_plan(PRESETS[1])
    assert set(balanced['weights'])==set(legacy['weights'])==ALL_SENSOR_PIDS
    assert balanced['scheduling_goal']=='CORRELATED_DPF_TURBO_SCR_ALL_ELIGIBLE'
    w=balanced['weights'];n=sum(w.values());scheduler=PollScheduler()
    sequence=[scheduler.next(w,w,allow_discovery=True) for _ in range(n*20)]
    assert Counter(sequence)=={p:weight*20 for p,weight in w.items()}
    times={p:[i*.25 for i,x in enumerate(sequence) if x==p] for p in w}
    means={p:(v[-1]-v[0])/(len(v)-1) for p,v in times.items()}
    old_n=sum(legacy['weights'].values())
    for p in (0x71,0x83,0x85,0x88):
        assert means[p]<old_n/(4*legacy['weights'][p])
    # Every slow/config entry recurs; improvement has a visible budget cost.
    for p in w.keys()-CORRELATED_FAST-CORRELATED_CONTEXT:
        assert max(b-a for a,b in zip(times[p],times[p][1:]))<=n*.5
    last={};ages=[]
    for i,p in enumerate(sequence):
        if p==0x7A and {0x71,0x0B,0x0C,0x10}<=last.keys():
            ages.extend((i-last[c])*.25 for c in (0x71,0x0B,0x0C,0x10))
        last[p]=i
    assert ages and min(ages)>0 and max(ages)<=n/4
    assert 'not simultaneous' in balanced['cadence_tradeoff']


def test_receipt_names_roles_without_claiming_observed_or_simultaneous_samples():
    plan=constructed_plan(PRESETS[3]);r=AcquisitionReceipt(PRESETS[3],True,'2000-01-01T00:00:00+00:00')
    r.configure(plan,session_id='constructed',context_id='fresh',mode='SIMULATED',bitmap_evidence={},rate=9)
    assert r.data['rate_limit']==4 and not r.data['effective_schedule'] and not r.data['observed']
    assert r.data['proposed_schedule']['71']['role']=='FAST_DYNAMIC'
    assert r.data['proposed_schedule']['83']['role']=='CORRELATION_CONTEXT'
    assert r.data['proposed_schedule']['4F']['role']=='RECURRING_STATUS_OR_LEGACY_WEIGHT'
    assert not auto_plan({}, {}, {}, '7E9',prepared=True,consent=True,preset=PRESETS[3])['weights']
