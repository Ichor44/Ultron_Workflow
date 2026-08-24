NAME = "sys_info"
DESCRIPTION = "Report basic operating system and environment information."
TRIGGERS = ["system info", "what OS", "computer specs", "environment"]

import os
import platform
import sys


def run(**kwargs):
    lines = [
        "System: %s %s" % (platform.system(), platform.release()),
        "Machine: %s" % platform.machine(),
        "Processor: %s" % platform.processor(),
        "Python: %s" % sys.version.split()[0],
        "Current user: %s" % os.getlogin(),
        "Working dir: %s" % os.getcwd(),
    ]
    return "\n".join(lines)
