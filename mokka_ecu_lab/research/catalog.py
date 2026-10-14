"""Versioned local knowledge base. Data never configures a live decoder/policy."""
import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from mokka_ecu_lab.sensors.diesel import STANDARD_DIESEL, RESEARCH_CANDIDATES
from mokka_ecu_lab.capture import DECODER_VERSION
from mokka_ecu_lab.sensors import load_registry
from .roadmap import research_roadmap

SCHEMA_VERSION = 1
STATUSES = ('STANDARD_DOCUMENTED','VEHICLE_OBSERVED','EXPERIMENTAL','UNVERIFIED_LAYOUT',
            'REJECTED','INDEPENDENTLY_VERIFIED')


def new_catalog():
    basic=[dict(s.metadata,request=f'01{s.pid:02X}',source=s.metadata['evidence'],edition='UNSPECIFIED',
        source_response_identifier='UNKNOWN',evidence_state='STANDARD_DOCUMENTED',vehicle_verification='UNVERIFIED',
        flags='No field support flag',sentinel_handling='No sentinel implemented in this definition',
        last_verification_time=None,test_provenance='Constructed fixtures; tests/test_sensors.py') for s in load_registry().values()]
    return dict(schema_version=SCHEMA_VERSION,definition_revision=DECODER_VERSION,cloud_upload=False,
        profile=dict(make='Opel',model='Mokka',year=2022,engine_family='Diesel; exact family UNKNOWN',
            ecu_family='UNKNOWN',hardware_identification='UNKNOWN',software_identification='UNKNOWN',
            calibration_identification='UNKNOWN',confidence='PROVISIONAL',identity_source=None),
        standard_definitions=basic+[dict(s.metadata(),source_response_identifier='UNKNOWN',
            evidence_state='STANDARD_DOCUMENTED',last_verification_time=None,
            test_provenance='Constructed fixtures; tests/test_diesel_decoders.py and tests/test_scr_decoder.py')
            for s in STANDARD_DIESEL.values()],
        manufacturer_candidates=[dict(c,evidence_state='EXPERIMENTAL',exact_payload_length=None,
            units='UNKNOWN',signedness='UNKNOWN',flags='UNKNOWN',sentinel_handling='UNKNOWN',
            last_verification_time=None) for c in RESEARCH_CANDIDATES],
        evidence=[],hypotheses=[],research_roadmap=research_roadmap(),
        limitations='No VIN lookup or ECU identification queries. Shared make/engine/ECU families do not establish DID compatibility. Definitions and evidence states never grant transmit permissions.')


class KnowledgeBase:
    def __init__(self,path):
        self.path = Path(path)
        if self.path.exists():
            if self.path.stat().st_size > 8*1024*1024: raise ValueError('Oversized local catalog')
            self.data = json.loads(self.path.read_text(encoding='utf-8'))
            if self.data.get('schema_version') != SCHEMA_VERSION: raise ValueError('Unsupported catalog version')
            if self.data.get('cloud_upload') is not False: raise ValueError('Catalog must remain local')
            template=new_catalog()
            if not isinstance(self.data.get('profile'),dict) or not template['profile'].keys()<=self.data['profile'].keys():
                raise ValueError('Invalid local profile')
            if any(not isinstance(self.data.get(k),list) for k in ('evidence','hypotheses')):
                raise ValueError('Invalid local evidence catalog')
            self.data.update(standard_definitions=template['standard_definitions'],
                research_roadmap=template['research_roadmap'],
                manufacturer_candidates=template['manufacturer_candidates'],definition_revision=DECODER_VERSION)
        else: self.data = new_catalog()

    def save(self):
        content=json.dumps(self.data,ensure_ascii=False,indent=2)+'\n'
        if len(content.encode())>8*1024*1024: raise ValueError('Local catalog exceeds 8 MiB limit')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix='catalog-',suffix='.json',dir=self.path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as stream: stream.write(content)
            os.replace(name,self.path)
        finally:
            if os.path.exists(name): os.unlink(name)

    def record_evidence(self,report):
        # Summaries only here. Raw bytes/timestamps remain in local analysis and
        # original bundles; observation does not modify documented definitions.
        evidence=[]
        for session in report['sessions']:
            for group in session['groups']:
                evidence.append(dict(evidence_id=session['evidence_id'],ecu=group['ecu'],mode=group['mode'],
                    source_kind=group['source_kind'],supported_standard_pids=[e['pid'] for e in group['matrix'] if e['support']=='SUPPORTED'],
                    payload_lengths={e['pid']:e['lengths'] for e in group['matrix'] if e['lengths']},
                    evidence_state='VEHICLE_OBSERVED' if group['source_kind']=='ECU_READING' else group['source_kind'],
                    independent_verification='UNVERIFIED',last_import_time=datetime.now(timezone.utc).isoformat(),
                    test_provenance='Original local bundle checksums; current offline analyzer '+report['decoder_version']))
        identities={e['evidence_id'] for e in evidence}
        self.data['evidence']=[e for e in self.data['evidence'] if e['evidence_id'] not in identities]+evidence
        self.save()

    def add_hypothesis(self,report):
        if report.get('verification') != 'EXPERIMENTAL': raise ValueError('Hypotheses must remain EXPERIMENTAL')
        for key in ('scale','offset'):
            if not math.isfinite(report[key]): raise ValueError('Finite formula required')
        self.data['hypotheses'].append(dict(report,evidence_state='EXPERIMENTAL',live_enabled=False,
            independent_verification='UNVERIFIED',saved_at=datetime.now(timezone.utc).isoformat()))
        self.save()

    def set_known_identity(self,values,source,verification_method):
        allowed={'engine_family','ecu_family','hardware_identification','software_identification','calibration_identification'}
        if not values or set(values)-allowed or not source.strip() or not verification_method.strip():
            raise ValueError('Independently known identity fields and source/method required; no VIN')
        if any(not isinstance(v,str) or not v.strip() or len(v)>256 for v in values.values()):
            raise ValueError('Invalid identity metadata')
        self.data['profile'].update(values,identity_source=source,
            identity_verification_method=verification_method,last_identity_verification_time=datetime.now(timezone.utc).isoformat())
        # Knowing a calibration identifier does not verify proprietary layouts.
        self.save()

    def reject_hypothesis(self,index,reason):
        if not reason.strip(): raise ValueError('Rejection reason required')
        self.data['hypotheses'][index].update(evidence_state='REJECTED',rejection_reason=reason.strip())
        self.save()


def validate_contribution(definition):
    """Future definition-only format; no uploader, account or promotion action."""
    allowed={'schema_version','definition_id','service','pid','length','formula','units','signed',
             'flags','sentinel','references','revision','evidence_state','verification_method','test_provenance'}
    if set(definition)!=allowed or definition['schema_version']!=SCHEMA_VERSION:
        raise ValueError('Only versioned definition metadata is allowed; no vehicle identity or recordings')
    if definition['evidence_state']!='INDEPENDENTLY_VERIFIED' or not definition['verification_method'] or not definition['references']:
        raise ValueError('Independent verification metadata required; this does not promote a local decoder')
    if not isinstance(definition['length'],int) or isinstance(definition['length'],bool) or not 1<=definition['length']<=4095:
        raise ValueError('Exact payload length required')
    if type(definition['signed']) is not bool or not all(isinstance(definition[k],str) and definition[k] for k in
        ('definition_id','service','pid','formula','units','revision','verification_method','test_provenance')):
        raise ValueError('Invalid definition metadata')
    if not isinstance(definition['flags'],dict) or not isinstance(definition['references'],list):
        raise ValueError('Invalid flags/references')
    if (type(definition['schema_version']) is not int or not re.fullmatch('[0-9A-F]{2}',definition['service'])
        or not re.fullmatch('[0-9A-F]{2,4}',definition['pid'])
        or any(not isinstance(v,str) for v in definition['flags'].values())
        or any(not isinstance(v,str) or not v.strip() for v in definition['references'])
        or definition['sentinel'] is not None and not isinstance(definition['sentinel'],str)):
        raise ValueError('Invalid definition metadata structure')
    return dict(definition)
