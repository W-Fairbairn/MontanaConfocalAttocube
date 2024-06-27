"""
hello_qua.py: template for basic qua program demonstration
"""
import math
import time
from qm import SimulationConfig, LoopbackInterface
from qm.qua import *
from qm.QuantumMachinesManager import QuantumMachinesManager
from configuration_TUTORIAL import *
from qm import generate_qua_script
import matplotlib.pyplot as plt
from JM.configuration_TUTORIAL import config

###################
# The QUA program #
###################
relaxation_time=250
measurement_length = 500 # nanoseconds

with program() as hello_QUA:
    tau = declare(int)
    a = declare(fixed)
    test = declare(bool, value=True)
    with infinite_loop_():
        with for_(tau, 10, tau < 100, tau+10):
            with for_(a, 0.1, a < 1, a + 0.1):

                play('x180', 'NV')
                wait(tau, 'NV')
                play('x180'*amp(a), 'NV')
                wait(250, 'NV')

                align('AOM', 'NV', 'SPCM')

                play('laser_ON', 'AOM', duration=1000)
                measure('readout', 'SPCM', None)


#####################################
#  Open Communication with the QOP  #
#####################################
qmm = QuantumMachinesManager(qop_ip, cluster_name=cluster_name)  # remove octave flag if not using it
# qmm = QuantumMachinesManager(qop_ip, opx_port)

simulate = True

if simulate:
    simulation_config = SimulationConfig(
        duration=28000, simulation_interface=LoopbackInterface([("con1", 3, "con1", 1)])  # in clock cycle
    )
    job_sim = qmm.simulate(config, hello_QUA, simulation_config)
    # Simulate blocks python until the simulation is done
    job_sim.get_simulated_samples().con1.plot()
    plt.show()
else:
    qm = qmm.open_qm(config)
    job = qm.execute(hello_QUA)
    # sourceFile = open('digital_element_debug.py', 'w')
    # print(generate_qua_script(hello_QUA, config), file=sourceFile)
    # sourceFile.close()

    # # Execute does not block python! As this is an infinite loop, the job would run forever. In this case, we've put a 10
    # # seconds sleep and then halted the job.
    # time.sleep(10)
    # job.halt()
