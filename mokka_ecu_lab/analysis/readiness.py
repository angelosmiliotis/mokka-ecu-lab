"""Pure offline 0101 readiness interpretation; never registered for LIVE requests.

Byte positions: J1979 APR2002 B2/B3 (public incorporated standard).
Ignition-specific monitor labels and B3 selector: EPA March 2013 Table 2.
This composite is not a claim to possess the licensed 2026 digital annex.
"""
SOURCE='https://law.resource.org/pub/us/cfr/ibr/005/sae.j1979.2002.pdf'
IGNITION_SOURCE='https://www.epa.gov/system/files/documents/2022-08/diesel-obd-im-readiness-14k-pounds-gwr-best-practices.pdf'
DEFINITION=dict(request='0101',name='Monitor status since DTCs cleared',expected_bytes=4,
    revision='APR2002 B2/B3 byte basis + EPA March2013 Table2 ignition mapping',source=[SOURCE,IGNITION_SOURCE],
    state='DOCUMENTED_COMPOSITE_OFFLINE_ONLY',live_admitted=False,physical_calibration='UNVERIFIED',
    limitation='Readiness completion is not monitor success, absence of faults, DPF regeneration, soot or ash. No vehicle-positive example supplied.')
SPARK=('Catalyst','Heated catalyst','Evaporative system','Secondary air','Legacy A/C refrigerant','Oxygen sensor','Oxygen sensor heater','EGR/VVT')
COMPRESSION=('NMHC catalyst','NOx/SCR aftertreatment',None,'Boost pressure',None,'Exhaust gas sensor','PM filter','EGR/VVT')


def decode_readiness(payload):
    if not isinstance(payload,bytes) or len(payload)!=4:raise ValueError('Offline 0101 requires exactly four data bytes')
    a,b,c,d=payload
    if b&0x80:raise ValueError('0101 reserved B7 is set; layout unverified')
    compression=bool(b&8);labels=COMPRESSION if compression else SPARK
    if compression and (c|d)&0x14:raise ValueError('0101 reserved compression monitor bits are set; layout unverified')
    monitors=[]
    def append(name,support,incomplete,location):
        monitors.append(dict(name=name,supported=bool(support),incomplete_reported=bool(incomplete),
            readiness='NOT_SUPPORTED' if not support else 'NOT_COMPLETE' if incomplete else 'COMPLETE',
            complete=None if not support else not bool(incomplete),bit_location=location,
            interpretation='Completion since DTC clear; not fault-free certification or regeneration evidence'))
    for bit,name in enumerate(('Misfire','Fuel system','Comprehensive components')):append(name,b&(1<<bit),b&(1<<(bit+4)),f'B{bit} support / B{bit+4} incomplete')
    for bit,name in enumerate(labels):
        if name is not None:append(name,c&(1<<bit),d&(1<<bit),f'C{bit} support / D{bit} incomplete')
    return dict(definition=DEFINITION,ignition='COMPRESSION' if compression else 'SPARK_OR_LEGACY',
        mil_commanded_on=bool(a&0x80),emission_related_dtc_count=a&0x7f,monitors=monitors,
        physical_calibration='UNVERIFIED',live_admitted=False)
