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
from qbstyles import mpl_style
mpl_style(dark=True)
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
meas_len = meas_len_1

###################
# The QUA program #
###################
with program() as counter:
    times = declare(int, size=1000)  # QUA vector for storing the time-tags
    counts = declare(int)  # variable for number of counts of a single chunk
    total_counts = declare(int)  # variable for the total number of counts
    n = declare(int)  # number of iterations
    counts_st = declare_stream()  # stream for counts

    # Infinite loop to allow the user to work on the experimental set-up while looking at the counts
    with infinite_loop_():
        # Loop over the chunks to measure for the total integration time
        with for_(n, 0, n < n_count, n + 1):
            # Play the laser pulse...
            play("laser_ON", "AOM2")
            play("laser_ON", "AOM1")
            # ... while measuring the events from the SPCM
            measure("readout", "SPCM1", time_tagging.analog(times, meas_len, counts))
            # Increment the received counts
            assign(total_counts, total_counts + counts)

        # Save the counts
        save(total_counts, counts_st)
        assign(total_counts, 0)

    with stream_processing():
        counts_st.with_timestamps().save_all("counts")

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
    res_handles = job.result_handles
    counts_handle = res_handles.get("counts")
    counts_handle.wait_for_values(5)
    time = []
    counts = []
    points = 1000
    # Live plotting
    fig = plt.figure()
    interrupt_on_close(fig, job)  # Interrupts the job when closing the figure
    last_idx = 0

    while res_handles.is_processing():
        new_idx = counts_handle.count_so_far()
        new_counts = counts_handle.fetch(slice(last_idx, new_idx))
        last_idx = new_idx

        time.extend(new_counts["timestamp"] / 1E9)  # Convert timestamps to seconds
        counts.extend(new_counts["value"] / (meas_len*1E-9*n_count) / 1000) # Convert counts to kcps
        #print(new_counts["value"])
        #print(new_counts["timestamp"] / 1E9)
        #print("\n")
        plt.cla()
        if len(time) > points:
            counts = counts[-points:]
            time = time[-points:]

        average_counts = np.average(counts[-20:])  # Average of the last 20 counts
        if average_counts >= 1000:
            unit = "Mcps"
            average_counts /= 1000
        elif average_counts < 1:
            unit = "cps"
            average_counts *= 1000
        else:
            unit = "kcps"
        rolling_av_array = [sum(counts[max(0, i-9):i+1]) / min(10, i+1) for i in range(len(counts))]

        plt.plot(time[10:-10], counts[10:-10], 'b-', label='Counts')
        plt.plot(time[10:-10], rolling_av_array[10:-10], 'r-', label=f'Average: {average_counts:.2f} {unit}')
        upper_bound = max(counts)*1.1
        lower_bound = min(counts)*0.9
        if lower_bound == upper_bound:
            upper_bound += 5

        plt.ylim(lower_bound, upper_bound)
        plt.xlabel("Time [s]")
        plt.ylabel("Counts [kcps]")
        plt.title("Counter")
        plt.legend(loc='upper right')
        plt.pause(0.01)
