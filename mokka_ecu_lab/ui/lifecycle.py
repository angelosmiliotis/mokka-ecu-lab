"""Windows suspend notification; no power setting changes or device requests."""
import os
from PySide6.QtCore import QAbstractNativeEventFilter

class PowerSuspendFilter(QAbstractNativeEventFilter):
    def __init__(self,worker):
        super().__init__();self.worker=worker

    def nativeEventFilter(self,event_type,message):
        if os.name=='nt' and bytes(event_type) in (b'windows_generic_MSG',b'windows_dispatcher_MSG'):
            import ctypes
            from ctypes.wintypes import MSG
            msg=MSG.from_address(int(message))
            if msg.message==0x218 and msg.wParam==4: # WM_POWERBROADCAST / PBT_APMSUSPEND
                self.worker.submit('system_suspend')
        return False,0
