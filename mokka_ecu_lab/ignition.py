"""Descriptive existing-response context; no extra probes or fault diagnosis."""
class IgnitionContext:
    def __init__(self):self.rpm=None;self.rejections=[]
    def observe(self,record,readings):
        context=record.get('context_id');now=record['monotonic_ns']
        for reading in readings:
            if reading.get('sensor_id')=='rpm' and record['status']=='OK':self.rpm=dict(value=reading['value'],ecu=reading['ecu'],context=context,time=now)
        rejected=[r.get('ecu') for r in record.get('negative_responses',[]) if r.get('nrc')=='22']
        if record['status']=='ECU_NEGATIVE_RESPONSE' and len(rejected)==1:self.rejections=(self.rejections+[(context,rejected[0])])[-3:]
        else:self.rejections=[]
    def explanation(self,now):
        recent=self.rpm
        if len(self.rejections)==3 and len(set(self.rejections))==1 and recent and self.rejections[0]==(recent['context'],recent['ecu']) and recent['value']>0 and 0<=now-recent['time']<=30_000_000_000:
            return 'Possible engine/ignition off after recent running RPM; user confirmation required. Three Conditions Not Correct replies retained. Finish Session to save; not proof of transport saturation or hardware fault.'
        return 'Conditions Not Correct (7F 01 22); engine/ignition state unconfirmed. Original ECU errors retained; Finish Session to save.'
