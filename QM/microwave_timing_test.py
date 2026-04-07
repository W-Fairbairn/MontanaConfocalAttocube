"""
        COUNTER
The program consists in playing a laser pulse while performing time tagging continuously.
This allows measuring the received photons as a function of time while adjusting external parameters
to validate the experimental set-up.
"""
import numpy as np
from pathlib import Path
from qm import QuantumMachinesManager
from qm.qua import *
from qm import SimulationConfig
import matplotlib.pyplot as plt
from configuration import *
from qualang_tools.results.data_handler import DataHandler
from math import log10, ceil, floor
#import seaborn as sns
#from qbstyles import mpl_style
#mpl_style(dark=True)
def round_to_1(x):
    if x != 0:
        return round(x, -int(floor(log10(abs(x)))))
    else:
        return 0
##################
#   Parameters   #
##################
# Parameters Definition
n_count = 3000
meas_len = long_meas_len_1
n_avg = 100_000_000
time_arr_len = 1000

###################
# The QUA program #
###################
with program() as counter:
    times = declare(int, size=1000)  # QUA vector for storing the time-tags
    counts = declare(int)  # variable for number of counts of a single chunk
    total_counts = declare(int)  # variable for the total number of counts
    times = declare(int, size=time_arr_len)  # QUA vector for storing the time-tags
    times_ref = declare(int, size=time_arr_len)  # QUA vector for storing the time-tags of reference counts
    times_st = declare_stream()  # stream to save time tags of counts, ref
    n = declare(int)  # number of iterations
    i = declare(int)  # variable to sweep over time tags
    counts_st = declare_stream()  # stream for counts

    # Infinite loop to allow the user to work on the experimental set-up while looking at the counts
    with for_(n, 0, n < n_avg, n + 1):
        # Play the laser pulse...
        update_frequency("NV", 167 * u.MHz)
        align()
        play("laser_ON", "AOM2")
        measure("long_readout", "SPCM1", time_tagging.analog(times, meas_len, counts))

        wait(2500//4, "NV")
        play("x180" * amp(1), "NV", duration=1000//4)
        align()  # Play the laser pulse after the mw pulse
        save(counts, counts_st)
        with for_(i, 0, i < counts, i + 1):
            save(times[i], times_st)  # cant directly save QUA vector, loop and save each element separately

    with stream_processing():
        counts_st.with_timestamps().save("counts")
        times_st.buffer(time_arr_len).save("time_tags")  # save time tags buffer size should be larger than counts expected

#####################################
#  Open Communication with the QOP  #
#####################################
calibration_db_dir = Path(__file__).resolve().parent
qmm = QuantumMachinesManager(
    host=qop_ip,
    cluster_name=cluster_name,
    octave_calibration_db_path=calibration_db_dir,
)

#######################
# Simulate or execute #
#######################
simulate = False

if simulate:
    # Simulates the QUA program for the specified duration
    simulation_config = SimulationConfig(duration=10_000)  # In clock cycles = 4ns
    # Simulate blocks python until the simulation is done
    job = qmm.simulate(config, counter, simulation_config)
    # Get the simulated samples
    samples = job.get_simulated_samples()
    # Plot the simulated samples
    samples.con1.plot()
    # Get the waveform report object
    waveform_report = job.get_simulated_waveform_report()
    # Cast the waveform report to a python dictionary
    waveform_dict = waveform_report.to_dict()
    # Visualize and save the waveform report
    waveform_report.create_plot(samples, plot=True, save_path=str(Path(__file__).resolve()))
else:
    qm = qmm.open_qm(config, close_other_machines=True)
    job = qm.execute(counter)
    # Get results from QUA program
    results = fetching_tool(
        job, data_list=["counts", "time_tags"], mode="live"
    )

    fig, ax = plt.subplots()
    interrupt_on_close(fig, job)  # Interrupts the job when closing the figure
    time_tag_arr = np.zeros(meas_len)

    while results.is_processing():
        counts, time_tags = results.fetch_all()
        ax.cla()
        for i in time_tags:
            time_tag_arr[i] += 1  # Convert histogram of time tags to array for faster plotting, saving memory
        time_tags = []
        ax.plot(np.linspace(0, meas_len, meas_len), time_tag_arr[:])
        ax.set_xlabel("Time bins")
        ax.set_ylabel("Counts")
        plt.pause(0.1)
