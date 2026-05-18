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

# ===== CUSTOMIZE CONFIG HERE =====
# Override laser initialization length without modifying configuration.py
laser_duration = 4000 * u.ns  # Laser pulse duration - adjust this value to change laser on-time
# ==================================

long_meas_len_1 = 5000  # in clock cycles, should be long enough to capture all counts, can be adjusted based on expected count rates
meas_len = long_meas_len_1
n_avg = 5_000_000
time_arr_len = 100

# Update only the laser_ON_2 pulse in the config
config["pulses"]["laser_ON_2"]["length"] = laser_duration

rabi_frequency = 10 * u.MHz
ODMR_peak_freq = -89 * u.MHz
pi_pulse_len = (1 / (2 * rabi_frequency)) / 1e-9  # ns
config["octaves"][octave]["RF_outputs"][1]["gain"] = -5
print("pi", pi_pulse_len, "ns")
print("pi/2", pi_pulse_len / 2, "ns")
config["pulses"]["x180_pulse"]["length"] = (pi_pulse_len) // 4 * 4
config["pulses"]["x90_pulse"]["length"] = (pi_pulse_len / 2) // 4 * 4
config["pulses"]["-x90_pulse"]["length"] = (pi_pulse_len / 2) // 4 * 4
config["pulses"]["x270_pulse"]["length"] = (pi_pulse_len * 1.5) // 4 * 4


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
    counts2_st = declare_stream()  # stream for counts
    times2_st = declare_stream()  # stream to save time tags of counts, ref



    # Infinite loop to allow the user to work on the experimental set-up while looking at the counts
    update_frequency("NV", ODMR_peak_freq, keep_phase=True)
    with for_(n, 0, n < n_avg, n + 1):
        align()
        wait(100000)
        align()
        play("laser_ON", "AOM2")
        measure("readout", "SPCM1", time_tagging.analog(times, meas_len, counts))
        save(counts, counts_st)
        with for_(i, 0, i < counts, i + 1):
            save(times[i], times_st)  # save each timetag (relative to start of measure)

        wait(wait_between_runs * u.ns, "AOM2")  # wait in between iterations

        align()
        play("laser_ON", "AOM2")
        measure("readout", "SPCM1", time_tagging.analog(times, meas_len, counts))
        save(counts, counts2_st)
        with for_(i, 0, i < counts, i + 1):
            save(times[i], times2_st)  # save each timetag (relative to start of measure)

        wait(wait_between_runs * u.ns, "AOM2")  # wait in between iterations

    with stream_processing():
        counts_st.with_timestamps().save_all("counts")
        times_st.save_all("time_tags")
        counts2_st.with_timestamps().save_all("counts2")
        times2_st.save_all("time_tags2")

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
        job, data_list=["counts", "time_tags", "counts2", "time_tags2"], mode="live"
    )

    fig, ax = plt.subplots()
    interrupt_on_close(fig, job)  # Interrupts the job when closing the figure
    time_tag_arr = np.zeros(meas_len)
    time_tag_arr2 = np.zeros(meas_len)

    while results.is_processing():
        counts, time_tags, counts2, time_tags2 = results.fetch_all()
        ax.cla()

        rel_bins = np.asarray(time_tags, dtype=int)
        rel_bins = rel_bins[(rel_bins >= 0) & (rel_bins < meas_len)]
        rel_bins2 = np.asarray(time_tags2, dtype=int)
        rel_bins2 = rel_bins2[(rel_bins2 >= 0) & (rel_bins2 < meas_len)]

        for b in rel_bins:
            time_tag_arr[b] += 1
        for b in rel_bins2:
            time_tag_arr2[b] += 1

        ax.plot(np.arange(meas_len), time_tag_arr, label="Counts with wait")
        ax.plot(np.arange(meas_len), time_tag_arr2, color="orange", label="Counts no wait")
        ax.set_xlabel("Time since readout start [4 ns bins]")
        ax.set_ylabel("Counts")
        ax.legend()

        time_tag_arr[:] = 0
        time_tag_arr2[:] = 0
        plt.pause(1)
