"""Offline recorded comparisons. No transport and no interpolation or merging sources."""
import csv
import io
import math
import hashlib
import zipfile
from collections import defaultdict
from pathlib import Path

TREND_FIELDS = {'speed':'km/h','rpm':'rpm','maf':'g/s','sae_85_tank_level':'%',
                'sae_83_bank_1_sensor_1':'ppm','sae_83_bank_1_sensor_2':'ppm',
                'sae_83_bank_2_sensor_1':'ppm','sae_83_bank_2_sensor_2':'ppm',
                'sae_85_warning_time':'s','sae_85_consumption':'L/h','sae_85_demand':'L/h'}
MAX_BYTES = 64*1024*1024
MAX_ROWS = 250000


def load_trends(path):
    path=Path(path)
    if path.suffix.lower()=='.zip':
        with zipfile.ZipFile(path) as archive:
            info=archive.getinfo('measurements.csv')
            if info.file_size>MAX_BYTES: raise ValueError('CSV exceeds offline preview limit (64 MiB)')
            payload=archive.read(info)
            # Optional checksum verified without extracting any member paths.
            if 'SHA256SUMS.txt' in archive.namelist():
                if archive.getinfo('SHA256SUMS.txt').file_size>65536: raise ValueError('Oversized checksum list')
                checks=dict((name.strip(),digest) for digest,name in
                            (line.split(None,1) for line in archive.read('SHA256SUMS.txt').decode().splitlines()))
                if checks.get('measurements.csv')!=hashlib.sha256(payload).hexdigest():
                    raise ValueError('Measurements CSV checksum mismatch')
    else:
        if path.stat().st_size>MAX_BYTES: raise ValueError('CSV exceeds offline preview limit (64 MiB)')
        payload=path.read_bytes()
    return recorded_trends(csv.DictReader(io.StringIO(payload.decode('utf-8-sig'))))


def recorded_trends(rows):
    groups=defaultdict(lambda:defaultdict(list)); ignored=0
    for index,row in enumerate(rows):
        if index>=MAX_ROWS: raise ValueError('CSV exceeds offline preview limit (250000 rows)')
        sensor=row.get('sensor_id')
        if sensor not in TREND_FIELDS: continue
        try:
            value=float(row['value']); ns=int(row['monotonic_ns'])
            if not math.isfinite(value) or ns<0 or row['unit']!=TREND_FIELDS[sensor]: raise ValueError()
        except (KeyError,TypeError,ValueError): ignored+=1; continue
        key=(row.get('ecu') or 'UNKNOWN ECU',row.get('source_mode') or 'UNKNOWN MODE',row.get('source_kind') or 'UNKNOWN SOURCE')
        groups[key][sensor].append((ns,value))
    result=[]
    for key,fields in sorted(groups.items()):
        anchor=min(ns for samples in fields.values() for ns,_ in samples)
        series={}; summaries=[]
        for sensor,samples in sorted(fields.items()):
            samples.sort(); values=[v for _,v in samples]
            gaps=[(b[0]-a[0])/1e9 for a,b in zip(samples,samples[1:]) if b[0]>a[0]]
            series[sensor]=[((ns-anchor)/1e9,value) for ns,value in samples]
            static=len(set(values))==1
            note='One sample; no trend' if len(values)==1 else 'Static recorded value' if static else 'Recorded variation'
            if sensor=='sae_85_warning_time':
                note+='; counter alone cannot establish a current SCR warning or fault'
            if sensor=='sae_85_tank_level': note+='; quantization/variation is not measured fluid consumption'
            summaries.append(dict(sensor_id=sensor,unit=TREND_FIELDS[sensor],samples=len(values),
                minimum=min(values),maximum=max(values),distinct_values=len(set(values)),static=static,
                max_gap_seconds=max(gaps) if gaps else None,note=note))
        result.append(dict(ecu=key[0],mode=key[1],source_kind=key[2],series=series,summary=summaries))
    return dict(groups=result,ignored_invalid_rows=ignored,
                limitations='Independent sampling instants; plots show recorded points, without interpolation, paired peaks or a health verdict.')
