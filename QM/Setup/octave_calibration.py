"""
This file is used to run the Octave automatic mixer calibration.
"""

from qm import QuantumMachinesManager
from configuration import *
import numpy as np

qmm = QuantumMachinesManager(host=qop_ip, cluster_name=cluster_name, log_level="ERROR", octave_calibration_db_path=calibration_db_dir)
qm = qmm.open_qm(config)

elements = ["NV"]
IF_arr = np.linspace(-250 * u.MHz, 250 * u.MHz, 500)  # can provide many IFs for specific LO
for element in elements:
    for IF in IF_arr:
        print("-" * 37 + f" Calibrates {element}")
        qm.calibrate_element(element, {NV_LO_freq: (IF,)})  # can provide many IFs for specific LO
