from qm.qua import *
from qm import SimulationConfig
import matplotlib.pyplot as plt
from JM_Pulse_Sequence_Configuration import *
from qualang_tools.loops import from_array
from qm.octave import ClockMode
from qm import QuantumMachinesManager
from qm.octave import *
import time
import matplotlib.pyplot as plt

qmm = QuantumMachinesManager(host=qop_ip, port=qop_port, octave=octave_config)
###################
# The QUA program #
###################

# The time vector for varying the idle time in clock cycles (4ns)
#t_vec = np.arange(4, 1000000, 20)
#n_avg = 1000000

with program() as hahn_echo:
    play("cw", "NV")
    wait(100000000, "NV")
    play("cw", "NV")
    wait(100000000, "NV")
    play("cw", "NV")

qm = qmm.open_qm(config)
qm.octave.set_clock(octave, clock_mode=ClockMode.Internal)
#qm.octave.set_rf_output_gain("NV",gain_in_db = 20)
calibration = True
if calibration:
    elements = ["NV"]
    for element in elements:
        print("-" * 37 + f" Calibrates {element}")
        qm.calibrate_element(element, {NV_LO_freq: (NV_IF_freq,)})  # can provide many IFs for specific LO

job = qm.execute(hahn_echo)
#Execute does not block python! As this is an infinite loop, the job would run forever.
#In this case, we've put a 10 seconds sleep and then halted the job.



