"""Fresh development artifacts outside the checkout; retention is preview-only."""
from pathlib import Path
from datetime import datetime,timezone
import os,uuid

def cache_root():
    from mokka_ecu_lab import __version__
    return Path(os.environ.get('LOCALAPPDATA',Path.home()/'.cache'))/'MokkaECULab/Development'/('v'+__version__)

def fresh_output(purpose):
    if not purpose or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in purpose):raise ValueError('Simple development purpose required')
    existing=[p for p in cache_root().glob(purpose+'-*') if p.is_dir()]
    if len(existing)>=3:raise ValueError('Three '+purpose+' outputs exist; explicitly review/archive them or choose --output-dir. No automatic deletion.')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    return cache_root()/(purpose+'-'+stamp+'-'+uuid.uuid4().hex[:8])
