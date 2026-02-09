"""
       T1 MEASUREMENT
The program consists in measuring the photon counts (in |0> and |1> successively) received by the SPCM across
varying wait times either after initialization (start from |0>), or after a pi pulse (start from |1>).

The data is then post-processed to determine the thermal relaxation time T1.

Prerequisites:
    - Ensure calibration of the different delays in the system (calibrate_delays).
    - Having updated the different delays in the configuration.
    - Having updated the NV frequency, labeled as "NV_IF_freq", in the configuration.
    - Having set the pi pulse amplitude and duration in the configuration

Next steps before going to the next node:
    -
"""

from qm import QuantumMachinesManager
from qm.qua import *
from qm import SimulationConfig
import matplotlib.pyplot as plt
from configuration import *
from qualang_tools.loops import from_array
from qualang_tools.results.data_handler import DataHandler
import numpy as np
from pathlib import Path
import math

##################
#   Parameters   #
##################
# Parameters Definition
run_length = 30 * 1E6 // 4 #in clock cycles (4ns)
num_points = 15
t_vec = np.arange(500, run_length, np.floor(run_length/num_points))  # The wait time vector in clock cycles (4ns)
n_avg = 1000000  # The number averaging iterations

# Determine reference readout during single laser pulse
reference_wait = initialization_len_1 // 4 - 2 * meas_len_1 // 4 - 25  # in clock cycles
reference_readout = reference_wait >= 4

# Data to save
save_data_dict = {
    "n_avg": n_avg,
    "t_vec": t_vec,
    "config": config,
}

###################
# The QUA program #
###################
with program() as T1:
    counts = declare(int)  # saves number of photon counts
    counts_ref = declare(int)
    time_arr_len = 1000
    times = declare(int, size=time_arr_len)  # QUA vector for storing the time-tags
    times_st = declare_stream()
    times_ref = declare(int, size=time_arr_len)
    counts_st = declare_stream()  # stream for counts
    counts_ref_st = declare_stream()  # stream for counts
    t = declare(int)  # variable to sweep over in time
    t_sample = declare(int)
    assign(t_sample, t_vec[-1])
    n = declare(int)  # variable to for_loop
    i = declare(int)
    n_st = declare_stream()  # stream to save iterations
    times_val = declare(int)
    point_to_sample = 3

    # Spin initialization
    #play("laser_ON", "AOM2")
    #wait(wait_for_initialization * u.ns, "AOM2")

    # T1 sequence
    with for_(n, 0, n < n_avg, n + 1):
        with for_(*from_array(t, t_vec)):
            # wait the variable delay (in clock cycles)
            play("laser_ON", "AOM2")
            wait(wait_for_initialization * u.ns, "AOM2")
            align()
            wait(t)
            align()
            wait(950 // 4, "SPCM1")
            wait(70 // 4, "SPCM1")
            play("laser_ON", "AOM2")
            #with if_(t == t_sample):
            play("laser_ON", "AOM1")
            measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
            save(counts, counts_st)
            wait((initialization_len_1-2*meas_len_1-100) // 4, "SPCM1")
            measure("readout", "SPCM1", time_tagging.analog(times_ref, meas_len_1, counts_ref))
            save(counts_ref, counts_ref_st)  # save ref counts
            with for_(i, 0, i < counts, i + 1):
                #with if_(t == t_sample):
                save(times[i], times_st)
        save(n, n_st)  # save number of iteration inside for_loop

    with stream_processing():
        counts_st.buffer(len(t_vec)).average().save("counts")
        counts_st.buffer(len(t_vec)).save_all("raw_counts")
        counts_ref_st.buffer(len(t_vec)).average().save("counts_ref")
        counts_ref_st.buffer(len(t_vec)).save_all("raw_counts_ref")
        times_st.buffer(time_arr_len).save("time_tags")
        n_st.save("iteration")

#####################################
#  Open Communication with the QOP  #
#####################################
qmm = QuantumMachinesManager(host=qop_ip, cluster_name=cluster_name)

#######################
# Simulate or execute #
#######################
simulate = False

if simulate:
    # For debugging the waveform, it's often convenient to simulate a single iteration:
    #   n_avg = 1
    #   t_vec = np.array([some_short_delay_in_clock_cycles])
    # and reduce the duration accordingly.
    simulation_config = SimulationConfig(duration=3_000)  # In clock cycles = 4ns
    # Simulate blocks python until the simulation is done
    job = qmm.simulate(config, T1, simulation_config)
    # Get the simulated samples
    samples = job.get_simulated_samples()
    # Plot the simulated samples (this will show all pulses/traces produced by the program)
    samples.con1.plot()
    # Get the waveform report object
    waveform_report = job.get_simulated_waveform_report()
    # Cast the waveform report to a python dictionary
    waveform_dict = waveform_report.to_dict()
    # Visualize and save the waveform report
    waveform_report.create_plot(samples, plot=True, save_path=str(Path(__file__).resolve()))
else:
    # Open the quantum machine
    qm = qmm.open_qm(config, close_other_machines=True)
    # Send the QUA program to the OPX, which compiles and executes it
    job = qm.execute(T1)
    # Get results from QUA program
    results = fetching_tool(
        job, data_list=["counts", "counts_ref", "time_tags", "iteration"], mode="live"
    )
    # Live plotting
    fig, ((ax1,ax2), (ax3, ax4)) = plt.subplots(2, 2) #, sharex=True
    interrupt_on_close(fig, job)  # Interrupts the job when closing the figure
    total = 0
    time_tag_arr = np.zeros(meas_len_1)
    histogram_data = {t_idx: [] for t_idx in range(len(t_vec))}
    raw_counts = []
    raw_counts_ref = []
    while results.is_processing():
        # Fetch results
        try:
            counts, counts_ref, time_tags, iteration = results.fetch_all()
        except Exception as e:
            print (e)
            break
        # Compute normalized signals
        norm = counts/counts_ref
        # Progress bar
        progress_counter(iteration, n_avg, start_time=results.get_start_time())

        count_err = np.sqrt(counts*iteration)/iteration
        ref_err = np.sqrt(counts_ref*iteration)/iteration
        norm_err = norm*np.sqrt((count_err/counts)**2 + (ref_err/counts_ref)**2)

        # Plot data
        ax1.cla()
        ax1.errorbar(4 * t_vec / 1000000, norm, label="counts", yerr=norm_err, capsize=2, fmt='o')
        ax1.set_ylabel("Signal")
        ax1.set_title("T1 Decay")
        ax1.set_xlabel("Wait time [ms]")
        ax1.legend()

        ax2.cla()
        # time_tag_arr.extend(time_tags)
        for i in time_tags:
            time_tag_arr[i] += 1
        time_tags = []
        ax2.plot(np.linspace(0, meas_len_1, meas_len_1), time_tag_arr[:])

        ax3.cla()
        ax3.errorbar(4 * t_vec / 1000000, counts, yerr=count_err, capsize=2, fmt='o')
        ax3.set_ylabel("Signal")
        ax3.set_title("Counts")
        ax3.set_xlabel("Wait time [ms]")
        #ax2.legend()

        ax4.cla()
        ax4.errorbar(4 * t_vec / 1000000, counts_ref, yerr=ref_err, capsize=2, fmt='o')
        ax4.set_ylabel("Signal")
        ax4.set_title("Counts Ref")
        ax4.set_xlabel("Wait time [ms]")
        # ax3.legend()
        # Initialize histogram accumulator outside the loop (before while loop starts)



        plt.pause(0.1)


    results_raw = fetching_tool(
        job, data_list=["raw_counts", "raw_counts_ref"], mode="wait_for_all"
    )
    raw_counts, raw_counts_ref = results_raw.fetch_all()
    # Save results
    script_name = Path(__file__).name
    data_handler = DataHandler(root_data_folder="C:/Users/attocube/Documents/MontanaQudiAttocube/MontanaConfocalAttocube/JM/save_dir")
    save_data_dict.update({"counts_data": counts})
    save_data_dict.update({"t_vec": t_vec})
    save_data_dict.update({"iteration": np.array([int(iteration)])})
    save_data_dict.update({"time_tag_arr": time_tag_arr})
    save_data_dict.update({"counts_ref": counts_ref})
    save_data_dict.update({"raw_counts": np.array(raw_counts)})
    save_data_dict.update({"raw_counts_ref": np.array(raw_counts_ref)})
    data_handler.save_data(data=save_data_dict, name="_".join(script_name.split("_")[1:]).split(".")[0])