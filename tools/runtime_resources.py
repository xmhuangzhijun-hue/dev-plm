"""Read physical memory without spawning another process."""
import os

def available_memory_mb():
    if os.name!='nt':
        try:return os.sysconf('SC_AVPHYS_PAGES')*os.sysconf('SC_PAGE_SIZE')//(1024*1024)
        except (ValueError,OSError,AttributeError):return None
    import ctypes
    class MemoryStatus(ctypes.Structure):
        _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong),
            *[(name,ctypes.c_ulonglong) for name in ['total_physical','available_physical','total_pagefile','available_pagefile','total_virtual','available_virtual','available_extended_virtual']]]
    status=MemoryStatus();status.length=ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):return None
    return status.available_physical//(1024*1024)
