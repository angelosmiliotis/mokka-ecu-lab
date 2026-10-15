"""Reviewed OCT2011 Mode 01 proposals; exact layouts, no transport authority.

The code-owned policy is a separate stage. Historical calibration/vehicle
accuracy is not established by a successful generic response.
"""
from dataclasses import dataclass, asdict

SOURCE='https://saemobilus.sae.org/standards/j1979da_201110-j1979-da-digital-annex-e-e-diagnostic-test-modes'


@dataclass(frozen=True)
class ExtendedField:
    id: str
    name: str
    start: int
    size: int
    unit: str
    scale: float=1.
    offset: float=0.
    support_bit: int | None=None
    support_byte: int=0
    value_bit: int | None=None
    width: int=1
    signed: bool=False
    labels: tuple=()
    unavailable_codes: tuple=()
    def metadata(self):
        return dict(asdict(self),layout=','.join(chr(65+i) for i in range(self.start,self.start+self.size)),
            support=f'byte {self.support_byte}, bit {self.support_bit}' if self.support_bit is not None else 'PID support',
            formula=f'bits {self.value_bit}:{self.width}' if self.value_bit is not None else f'{"signed" if self.signed else "unsigned"} BE * {self.scale:g} + {self.offset:g}',
            validity='Exact complete layout; per-field flags; unknown/reserved enum values unavailable')


@dataclass(frozen=True)
class ExtendedPID:
    pid: int
    name: str
    system: str
    length: int
    table: str
    fields: tuple
    reserved: tuple=()
    def metadata(self):
        return dict(pid=f'{self.pid:02X}',request=f'01{self.pid:02X}',name=self.name,system=self.system,length=self.length,
            expected_response=f'41 {self.pid:02X} + {self.length} data bytes',source=SOURCE,source_table=self.table,
            edition='OCT2011',verification='STANDARD_DOCUMENTED',vehicle_verification='UNVERIFIED',
            request_bytes=2,fields=[f.metadata() for f in self.fields],stage='REVIEWED_IMPLEMENTATION; separate code-owned policy and current ECU gates',
            limitations='Read-only observation/status/configuration, not actuation or overall health. Exact vehicle calibration remains unverified.')
    def decode(self,payload):
        if len(payload)!=self.length:raise ValueError(f'PID {self.pid:02X}: expected exactly {self.length} bytes; layout unverified')
        if any(payload[i]&mask for i,mask in self.reserved):raise ValueError(f'PID {self.pid:02X}: reserved bits set')
        result=[]
        for f in self.fields:
            supported=f.support_bit is None or bool(payload[f.support_byte]&(1<<f.support_bit))
            encoded=((payload[f.start]>>f.value_bit)&((1<<f.width)-1) if f.value_bit is not None else int.from_bytes(payload[f.start:f.start+f.size],'big',signed=f.signed))
            known=encoded not in f.unavailable_codes and (not f.labels or encoded<len(f.labels) and f.labels[encoded] is not None)
            state='UNSUPPORTED_FIELD' if not supported else 'UNAVAILABLE_ENCODING' if not known else 'AVAILABLE'
            if self.pid==0x71 and ('command' in f.id or 'position' in f.id):
                bank_a='_a_' in f.id;flag=2 if bank_a else 5;shift=0 if bank_a else 2
                if payload[0]&(1<<flag) and (payload[5]>>shift)&3==3 and supported:state='UNRELIABLE_REPORTED_FAULT'
            value=encoded*f.scale+f.offset if state=='AVAILABLE' else None
            result.append(dict(f.metadata(),sensor_id=f'sae_{self.pid:02x}_{f.id}',state=state,value=value,
                display=f.labels[encoded] if value is not None and f.labels else value,
                verification='STANDARD_DOCUMENTED',vehicle_verification='UNVERIFIED'))
        return result


def scalar(pid,name,unit,length,scale=1.,offset=0.,table=''):
    return ExtendedPID(pid,name,'Standard measurements',length,table,(ExtendedField('value',name,0,length,unit,scale,offset),))


EXTENDED_STANDARD={p:scalar(p,n,u,l,s,o,t) for p,n,u,l,s,o,t in (
    (0x11,'Absolute throttle position','%',1,100/255,0,'B18'),
    (0x1F,'Time since engine start','s',2,1,0,'B26'),
    (0x21,'Distance while MIL activated','km',2,1,0,'B27'),
    (0x23,'Fuel rail gauge pressure','kPa gauge',2,10,0,'B29'),
    (0x2C,'Commanded EGR','%',1,100/255,0,'B32'),
    (0x2D,'EGR error relative to command','%',1,100/128,-100,'B33'),
    (0x30,'Warm-ups since DTC clear','count',1,1,0,'B36'),
    (0x31,'Distance since DTC clear','km',2,1,0,'B37'),
    (0x33,'Barometric absolute pressure','kPa abs',1,1,0,'B39'),
    (0x3C,'Catalyst temperature bank 1 sensor 1','°C',2,.1,-40,'B42'),
    (0x49,'Accelerator pedal position D','%',1,100/255,0,'B54'),
    (0x4A,'Accelerator pedal position E','%',1,100/255,0,'B55'),
    (0x4C,'Reported throttle actuator command','%',1,100/255,0,'B57'),
    (0x4D,'Engine time while MIL activated','min',2,1,0,'B58'),
    (0x4E,'Engine time since DTC clear','min',2,1,0,'B59'),
    (0x5E,'Average engine fuel rate','L/h',2,.05,0,'B75'))}

EXTENDED_STANDARD[0x1C]=ExtendedPID(0x1C,'OBD compliance encoding','Status',1,'B23',(
    ExtendedField('compliance','Reported OBD compliance',0,1,'code',labels=(None,'OBD II','OBD','OBD/OBD II','OBD I','No OBD','EOBD','EOBD/OBD II','EOBD/OBD','EOBD/OBD/OBD II','JOBD','JOBD/OBD II','JOBD/EOBD','JOBD/EOBD/OBD II',None,None,None,'EMD','EMD+','HD OBD-C','HD OBD','WWH OBD',None,'HD EOBD-I','HD EOBD-I N','HD EOBD-II','HD EOBD-II N',None,'OBDBr-1','OBDBr-2','KOBD','IOBD I','IOBD II','HD EOBD-VI')),))
EXTENDED_STANDARD[0x51]=ExtendedPID(0x51,'Reported fuel type','Status',1,'B62',(
    ExtendedField('fuel_type','Reported fuel type',0,1,'code',labels=(None,'Gasoline','Methanol','Ethanol','Diesel','LPG','CNG','Propane','Electric','Bi-fuel gasoline','Bi-fuel methanol','Bi-fuel ethanol','Bi-fuel LPG','Bi-fuel CNG','Bi-fuel propane','Bi-fuel electric','Bi-fuel mixed','Hybrid gasoline','Hybrid ethanol','Hybrid diesel','Hybrid electric','Hybrid mixed','Hybrid regeneration mode','Bi-fuel diesel')),))
EXTENDED_STANDARD[0x4F]=ExtendedPID(0x4F,'Decoder range configuration 1','Configuration',4,'B60',tuple(
    ExtendedField(n,label,i,1,u,s) for i,n,label,u,s in ((0,'equivalence_max','Equivalence range selector','selector',1),(1,'oxygen_voltage_max','Oxygen voltage range selector','V',1),(2,'oxygen_current_max','Oxygen current range selector','mA',1),(3,'map_max','MAP maximum range; zero selects default','kPa abs',10))))
EXTENDED_STANDARD[0x50]=ExtendedPID(0x50,'Decoder range configuration 2','Configuration',4,'B61',(
    ExtendedField('maf_max','MAF maximum range; zero selects default',0,1,'g/s',10),),((1,255),(2,255),(3,255)))
EXTENDED_STANDARD[0x71]=ExtendedPID(0x71,'Variable geometry turbo position and status','Turbo',6,'B93',(
    ExtendedField('vgt_a_command','VGT A reported command',1,1,'%',100/255,support_bit=0),
    ExtendedField('vgt_a_position','VGT A reported position',2,1,'%',100/255,support_bit=1),
    ExtendedField('vgt_b_command','VGT B reported command',3,1,'%',100/255,support_bit=3),
    ExtendedField('vgt_b_position','VGT B reported position',4,1,'%',100/255,support_bit=4),
    ExtendedField('vgt_a_status','VGT A reported loop status',5,1,'code',support_bit=2,value_bit=0,width=2,labels=(None,'Open loop','Closed loop','Fault reported; position unreliable')),
    ExtendedField('vgt_b_status','VGT B reported loop status',5,1,'code',support_bit=5,value_bit=2,width=2,labels=(None,'Open loop','Closed loop','Fault reported; position unreliable'))),((0,0xC0),(5,0xF0)))
EXTENDED_STANDARD[0x8C]=ExtendedPID(0x8C,'Wide-range oxygen concentration and lambda','Exhaust',17,'B119',tuple(
    ExtendedField(f'bank_{bank}_sensor_{sensor}_{kind}',f'Oxygen {kind} bank {bank} sensor {sensor}',1+2*i,2,unit,scale,support_bit=i)
    for i,(kind,unit,scale,bank,sensor) in enumerate((kind,unit,scale,b,s) for kind,unit,scale in (('concentration','%',.001526),('lambda','ratio',.000122)) for b,s in ((1,1),(1,2),(2,1),(2,2)))))
EXTENDED_STANDARD[0x8F]=ExtendedPID(0x8F,'Particulate sensor status and normalized signal','Exhaust',7,'B122',tuple(
    f for bank,status_byte,signal_byte,status_flag,signal_flag in ((1,1,2,0,1),(2,4,5,2,3)) for f in (
        ExtendedField(f'bank_{bank}_active',f'PM sensor bank {bank} actively measuring',status_byte,1,'state',support_bit=status_flag,value_bit=0),
        ExtendedField(f'bank_{bank}_sensor_regenerating',f'PM SENSOR bank {bank} regeneration; not DPF regeneration',status_byte,1,'state',support_bit=status_flag,value_bit=1),
        ExtendedField(f'bank_{bank}_normalized',f'PM sensor bank {bank} normalized signal; not DPF soot mass',signal_byte,2,'%',.01,support_bit=signal_flag,signed=True))),((0,0xF0),(1,0xFC),(4,0xFC)))

# Monitor/status decoding is available offline. It is intentionally outside this
# release's live extension until its complete mode-specific semantics are reviewed.
UNIMPLEMENTED_STANDARD={0x01:dict(name='Monitor status since DTC clear',edition='OCT2011',table='B2',length=4,reason='Full ignition-specific readiness decoder not implemented; no live request'),
    0x9D:dict(name='PID 019D — definition not verified',edition=None,table=None,length=None,reason='Not defined in consulted OCT2011 annex; newer primary layout required; no live request')}


def basic_range(sensor,payload,configuration,advertised=()):
    """Apply only current same-ECU observed configuration; zero selects default."""
    value=sensor.decode(payload)
    required={0x0B:0x4F,0x10:0x50}.get(sensor.pid)
    if required in advertised and required not in configuration:raise ValueError('Advertised range configuration has no valid current same-ECU response; numeric scaling unavailable')
    if sensor.pid==0x0B and configuration.get(0x4F):
        selector=configuration[0x4F][3]
        if selector:value=payload[0]*selector*10/255
    if sensor.pid==0x10 and configuration.get(0x50):
        selector=configuration[0x50][0]
        if selector:value=int.from_bytes(payload[:2],'big')*selector*10/65535
    return value
