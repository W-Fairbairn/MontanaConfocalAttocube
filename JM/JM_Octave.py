"""
hello_octave.py: template for basic usage of the Octave
"""
from qm.octave import ClockMode
from qm import QuantumMachinesManager
from qm.qua import *
from qm.octave import *
from JM_Octave_configuration import *
from qm import SimulationConfig
import time
import matplotlib.pyplot as plt

###################################
# Open Communication with the QOP #
###################################
qmm = QuantumMachinesManager(host=qop_ip, port=qop_port, octave=octave_config)

###################
# The QUA program #
###################
n = 1
total = 10
with program() as hello_octave:
    play("readout" * amp(2), "qe1")
    frame_rotation_2pi(0.25, "qe1")
    with infinite_loop_():
        while n < total:
            play("cw" * amp(2), "qe1")
            wait(4)
            frame_rotation_2pi(0.5, "qe1")
            play("jm" * amp(2), "qe1")
            wait(4)
            n = n+1
    frame_rotation_2pi(-0.25, "qe1")
    play("readout" * amp(2), "qe1")



#######################################
# Execute or Simulate the QUA program #
#######################################
simulate = False
if simulate:
    simulation_config = SimulationConfig(duration=300)  # in clock cycles
    job_sim = qmm.simulate(config, hello_octave, simulation_config)
    job_sim.get_simulated_samples().con1.plot()
    samples = job_sim.get_simulated_samples()
    print(samples.con1)
    samples.con1.plot()
    plt.legend('')
    plt.show()

else:
    qm = qmm.open_qm(config)
    qm.octave.set_clock(octave, clock_mode=ClockMode.Internal)
    calibration = True
    if calibration:
        elements = ["qe1"]
        for element in elements:
            print("-" * 37 + f" Calibrates {element}")
            qm.calibrate_element(element, {LO: (IF,)})  # can provide many IFs for specific LO
    job = qm.execute(hello_octave)
    #Execute does not block python! As this is an infinite loop, the job would run forever.
    #In this case, we've put a 10 seconds sleep and then halted the job.
    time.sleep(10)
    job.halt()

