"""Code-owned SAE J1979-DA OCT2011 diesel field layouts.

The consulted primary annex is referenced by table, not redistributed. Every
field remains unverified on this vehicle. Discovery never changes the basic
dashboard registry or authorizes an OEM command.
"""
from dataclasses import dataclass, asdict

SAE = 'https://saemobilus.sae.org/standards/j1979da_201110-j1979-da-digital-annex-e-e-diagnostic-test-modes'
ANNEX = 'https://www.e90post.com/forums/attachment.php?attachmentid=1509324&d=1476497126'
DASHLOGIC = 'https://www.dashlogic.com/docs/technical/obdii_pids'


@dataclass(frozen=True)
class Field:
    id: str
    name: str
    start: int
    size: int
    unit: str
    scale: float = 1.
    offset: float = 0.
    support_bit: int | None = None
    value_bit: int | None = None
    signed: bool = False
    labels: tuple[str, str] | None = None

    def metadata(self):
        d = asdict(self)
        d['layout'] = ','.join(chr(65+i) for i in range(self.start, self.start+self.size))
        d['support'] = f'A bit {self.support_bit}' if self.support_bit is not None else 'PID support; no field flag'
        d['formula'] = f'bit {self.value_bit}' if self.value_bit is not None else f'{"signed" if self.signed else "unsigned"} big-endian * {self.scale:g} + {self.offset:g}'
        d['validity'] = 'Complete documented layout; ECU PID support and field support flag when present'
        return d


@dataclass(frozen=True)
class DieselPID:
    pid: int
    name: str
    system: str
    length: int
    table: str
    fields: tuple[Field, ...]
    reserved_mask: int = 0

    def metadata(self):
        return {'pid': f'{self.pid:02X}', 'request': f'01{self.pid:02X}',
                'expected_response': f'41 {self.pid:02X} + {self.length} data bytes',
                'system': self.system, 'name': self.name, 'length': self.length,
                'verification': 'STANDARD_DOCUMENTED', 'vehicle_verification': 'UNVERIFIED',
                'source': SAE, 'annex_copy': ANNEX, 'source_table': self.table,
                'cross_check': DASHLOGIC, 'edition': 'OCT2011', 'source_ecu': 'Response CAN ID; never inferred from vehicle model',
                'fields': [f.metadata() for f in self.fields],
                'limitations': 'No blockage percentage or universal health threshold. Historical standard layout; other lengths/revisions require evidence.'}

    def decode(self, payload: bytes) -> list[dict]:
        if len(payload) != self.length:
            raise ValueError(f'PID {self.pid:02X}: expected exactly {self.length} bytes (OCT2011 layout), received {len(payload)}; layout unverified')
        if payload[0] & self.reserved_mask:
            raise ValueError(f'PID {self.pid:02X}: reserved support/status bits set; layout unverified')
        if self.pid == 0x8B and payload[1] & 0xF0:
            raise ValueError('PID 8B: reserved status bits set')
        if self.pid == 0x88 and not payload[0] & 0x80 and payload[0] & 0x0F:
            raise ValueError('PID 88: inducement reasons without active state')
        values = []
        for field in self.fields:
            supported = field.support_bit is None or bool(payload[0] & (1 << field.support_bit))
            value = None
            if supported:
                value = ((payload[field.start] >> field.value_bit) & 1 if field.value_bit is not None
                         else int.from_bytes(payload[field.start:field.start+field.size], 'big', signed=field.signed)*field.scale+field.offset)
            values.append(dict(field.metadata(), sensor_id=f'sae_{self.pid:02x}_{field.id}',
                               value=value, state='AVAILABLE' if supported else 'UNSUPPORTED_FIELD',
                               verification='STANDARD_DOCUMENTED', vehicle_verification='UNVERIFIED',
                               display=field.labels[int(value)] if value is not None and field.labels else value))
        return values


def pairs(names, unit, scale=1., offset=0., signed_first=False):
    return tuple(Field(name.lower().replace(' ', '_'), name, 1+2*i, 2, unit, scale, offset, i,
                       signed=signed_first and i == 0) for i, name in enumerate(names))


STANDARD_DIESEL = {
    0x73: DieselPID(0x73, 'Exhaust pressure', 'Exhaust', 5, 'B95', pairs(['Bank 1 pressure', 'Bank 2 pressure'], 'kPa', .01), 0xFC),
    0x78: DieselPID(0x78, 'Exhaust gas temperatures, Bank 1', 'Exhaust', 9, 'B100', pairs([f'Bank 1 sensor {i}' for i in range(1,5)], '°C', .1, -40), 0xF0),
    0x79: DieselPID(0x79, 'Exhaust gas temperatures, Bank 2', 'Exhaust', 9, 'B101', pairs([f'Bank 2 sensor {i}' for i in range(1,5)], '°C', .1, -40), 0xF0),
    0x7A: DieselPID(0x7A, 'DPF pressures, Bank 1', 'DPF', 7, 'B102', pairs(['Delta pressure', 'Inlet pressure', 'Outlet pressure'], 'kPa', .01, signed_first=True), 0xF8),
    0x7B: DieselPID(0x7B, 'DPF pressures, Bank 2', 'DPF', 7, 'B103', pairs(['Delta pressure', 'Inlet pressure', 'Outlet pressure'], 'kPa', .01, signed_first=True), 0xF8),
    0x7C: DieselPID(0x7C, 'DPF temperatures', 'DPF', 9, 'B104', pairs(['Bank 1 inlet', 'Bank 1 outlet', 'Bank 2 inlet', 'Bank 2 outlet'], '°C', .1, -40), 0xF0),
    0x7F: DieselPID(0x7F, 'Engine cumulative run times', 'Engine', 13, 'B107', tuple(Field(n, n.replace('_',' '), 1+4*i, 4, 's', support_bit=i) for i,n in enumerate(['total_engine_time','idle_time','pto_time'])), 0xF8),
    0x83: DieselPID(0x83, 'NOx concentrations', 'SCR/AdBlue', 9, 'B110', pairs(['Bank 1 sensor 1', 'Bank 1 sensor 2', 'Bank 2 sensor 1', 'Bank 2 sensor 2'], 'ppm'), 0xF0),
    0x85: DieselPID(0x85, 'NOx reagent system', 'SCR/AdBlue', 10, 'B112', (
        Field('consumption','Average reagent consumption',1,2,'L/h',.005,support_bit=0),
        Field('demand','Average demanded reagent consumption',3,2,'L/h',.005,support_bit=1),
        Field('tank_level','Reagent tank level',5,1,'%',100/255,support_bit=2),
        Field('warning_time','Engine time in NOx warning mode',6,4,'s',support_bit=3)), 0xF0),
    # DashLogic has a mg/mm³ typo; primary SAE B113 explicitly specifies mg/m³.
    0x86: DieselPID(0x86, 'Particulate matter concentrations', 'Exhaust', 5, 'B113', pairs(['Bank 1 sensor 1','Bank 2 sensor 1'], 'mg/m³', .0125), 0xFC),
    0x88: DieselPID(0x88, 'SCR inducement state and history', 'SCR/AdBlue', 3, 'B115', (
        Field('active','Inducement active',0,1,'state',value_bit=7,labels=('Inactive','Active')),
        *(Field(n,n.replace('_',' '),0,1,'state',value_bit=i) for i,n in enumerate(['low_reagent','incorrect_reagent','consumption_deviation','high_nox'])),
        *(Field(f'history_{j}_{i}',f'{block} {n}',1+(j//2),1,'state',value_bit=(j%2)*4+i)
          for j,block in enumerate(['0–10k km','10–20k km','20–30k km','30–40k km'])
          for i,n in enumerate(['low reagent','incorrect reagent','consumption deviation','high NOx']))), 0x70),
    0x8B: DieselPID(0x8B, 'Diesel aftertreatment', 'DPF', 7, 'B118', (
        Field('regeneration','DPF regeneration in progress',1,1,'state',support_bit=0,value_bit=0,labels=('Not in progress','In progress')),
        Field('regeneration_type','DPF regeneration type',1,1,'state',support_bit=1,value_bit=1,labels=('Passive','Active')),
        Field('nox_regeneration','NOx adsorber regeneration',1,1,'state',support_bit=2,value_bit=2),
        Field('desulfurization','NOx adsorber desulfurization',1,1,'state',support_bit=3,value_bit=3),
        Field('normalized_trigger','Normalized regeneration trigger',2,1,'%',100/255,support_bit=4),
        Field('average_time','Average time between successful active regenerations',3,2,'min',support_bit=5),
        Field('average_distance','Average distance between successful active regenerations',5,2,'km',support_bit=6)), 0x80),
}

RESEARCH_CANDIDATES = tuple({'request': request, 'name': name, 'system': 'DPF', 'ecu_family': 'Bosch MD1CS003 (reported; actual ECU unconfirmed)',
    'verification': 'RESEARCH_ONLY', 'support': 'UNVERIFIED', 'live_enabled': False,
    'formula': 'Unknown; no numeric decoder', 'source': 'https://www.forum-peugeot.com/Forum/threads/obd2-dpf.131744/',
    'evidence': 'VLud, 2 April 2023, post #19; no Mokka response or software/calibration identification'}
    for request,name in [('22D525','Reported average distance over last 10 regenerations'),('22D526','Reported estimated soot mass'),('22D52F','Reported estimated ash loading'),('22D532','Reported estimated deterioration')])
