
from qm import QuantumMachinesManager
from qm.qua import *
from qm import SimulationConfig
from qm.octave import *
import matplotlib.pyplot as plt
from JM_Pulse_Sequence_Configuration import *
from qualang_tools.loops import from_array
from qm.octave import ClockMode
import numpy as np

###################
# The QUA program #
###################
#Integration time for measuring counts for counts threshold loop
single_integration_time_ns = int(100 * u.us)  # The QM people set this to 500us. A longer time gives more counts for
# each value of 'counts' but increasing the time drastically increases the time taken for the experiment to acquire a reasonable
# signal-to-noise ratio. Set the integration time so that it either gives a signal of approximately zero counts when refocusing begins,
# or so that it gives a signal of approximately zero counts during the experiment and a sudden increase in counts during refocusing.
# Which one of these situations is chosen wil depend on the experiment.
single_integration_time_cycles = single_integration_time_ns // 4

# The time vector for varying the idle time in clock cycles (4ns)
# This cannot start from zero!
t_vec = np.arange(10, 1000000, 50000)
n_avg = 1000000  # The number of averaging iterations

# Threshold counts value above or below which (as chosen in the counter loop) the program pauses for refocusing.
counts_threshold = 10
# Threshold for how many iterations of 'n' 'counts' should be equal to 'counts_threshold' for the program to pause.
n_threshold = 3

with program() as T1:
    #Hahn-echo parameters
    counts1 = declare(int)  # saves number of photon counts
    counts2 = declare(int)  # saves number of photon counts
    counts_dark1 = declare(int)  # saves number of photon counts
    counts_dark2 = declare(int)  # saves number of photon counts
    times1 = declare(int, size=100)  # QUA vector for storing the time-tags
    times2 = declare(int, size=100)  # QUA vector for storing the time-tags
    times_dark1 = declare(int, size=100)  # QUA vector for storing the time-tags
    times_dark2 = declare(int, size=100)  # QUA vector for storing the time-tags
    counts_1_st = declare_stream()  # stream for counts
    counts_2_st = declare_stream()  # stream for counts
    counts_dark1_st = declare_stream()  # stream for counts
    counts_dark2_st = declare_stream()  # stream for counts
    t = declare(int)  # variable to sweep over in time
    n = declare(int)  # variable to for_loop
    b = declare(int)  # variable for refocusing loop
    n_st = declare_stream()  # stream to save iterations

    #Counter parameters
    times = declare(int, size=1000)  # QUA vector for storing the time-tags
    counts = declare(int)  # variable for number of counts of a single chunk
    counts_st = declare_stream()  # stream for counts

    #Counter for tracking consecutive below-threshold counts
    threshold_counter = declare(int, value=0)

    # Spin initialization
    play("laser_ON", "AOM1")
    wait(wait_for_initialization * u.ns, "AOM1")

    # T1 sequence
    with for_(n, 0, n < n_avg, n + 1):
        with for_(*from_array(t, t_vec)):
            wait(t, "NV")  # Variable idle time
            align()  # Play the laser pulse after the T1 sequence
            # Measure and detect the photons on SPCM1
            play("laser_ON", "AOM1")
            measure("readout", "SPCM1", time_tagging.analog(times1, meas_len_1, counts1))
            save(counts1, counts_1_st)  # save counts
            measure("long_readout", "SPCM2", time_tagging.analog(times_dark1, long_meas_len_2, counts_dark1))
            save(counts_dark1, counts_dark1_st)
            wait(wait_between_runs, "AOM1")

            align()
            # Loop for measuring raw photon counts in real time.
            # Play the laser pulse...
            play("laser_ON", "AOM1", duration=single_integration_time_cycles)
            #... while measuring the events from the SPCM
            measure("readout", "SPCM1", time_tagging.analog(times, single_integration_time_ns, counts))
            #Save the counts
            save(counts, counts_st)
            wait(wait_between_runs, "AOM1") # Added after last measurement - remove if problems appear in the next measurement.

        # Check the value of counts
        with if_(counts < counts_threshold):
            # Increment the counter
            assign(threshold_counter, threshold_counter + 1)
        with else_():
            # Reset the counter if counts is not equal to (below or above, as chosen) threshold
            assign(threshold_counter, 0)

        #with if_(n > 0):
            #with if_(n - (2 * (n / 2)) == 0): # Only even numbers of n are examined to see if the counts value is below/above the threshold.
                # This stops the program from pausing twice in a row.
                #with if_(counts < counts_threshold):

        # If the value of counts for 'n_threshold' consecutive iterations of the 'n' loop is equal to (or above or below, as chosen) the value of
        # 'counts_threshold', the loop below is invoked and the program pauses for refocusing.
        with if_(threshold_counter == n_threshold):
            with for_(b, 0, b < 3300, b + 1): # Time taken for optimisation is 31.90 seconds, laser pulse is 0.01 seconds.
                play("laser_ON_refocusing", "AOM1")
                # Reset the counter after the refocusing loop
            assign(threshold_counter, 0)

        save(n, n_st)  # save number of iteration inside for_loop

    with infinite_loop_():
        play("laser_ON_refocusing", "AOM1")

    with stream_processing():
        # Cast the data into a 1D vector, average the 1D vectors together and store the results on the OPX processor
        counts_1_st.buffer(len(t_vec)).average().save("counts1")
        #counts_2_st.buffer(len(t_vec)).average().save("counts2")
        counts_dark1_st.buffer(len(t_vec)).average().save("counts_dark1")
        #counts_dark2_st.buffer(len(t_vec)).average().save("counts_dark2")
        counts_st.with_timestamps().save("counts") # Store the values of counts being used for the threshold loop so that they can be printed
        # to allow for calibration of threshold value.
        n_st.save("iteration")

#####################################
#  Open Communication with the QOP  #
#####################################
qmm = QuantumMachinesManager(host=qop_ip, cluster_name=cluster_name, port=qop_port, octave=octave_config)

#######################
# Simulate or execute #
#######################
simulate = False

if simulate:
    # Simulates the QUA program for the specified duration
    simulation_config = SimulationConfig(duration=40_000)  # In clock cycles = 4ns
    job = qmm.simulate(config, T1, simulation_config)
    job.get_simulated_samples().con1.plot()
    plt.legend('')
    plt.show()
else:
    # Open the quantum machine
    qm = qmm.open_qm(config)
    qm.octave.set_clock(octave, clock_mode=ClockMode.Internal)
    calibration = True
    if calibration:
        elements = ["NV"]
        for element in elements:
            print("-" * 37 + f" Calibrates {element}")
            qm.calibrate_element(element, {NV_LO_freq: (NV_IF_freq,)})
    # Send the QUA program to the OPX, which compiles and executes it
    job = qm.execute(T1)
    # Get results from QUA program
    results = fetching_tool(job, data_list=["counts", "counts1", "counts_dark1", "iteration"], mode="live")

    # Live plotting
    fig = plt.figure()
    interrupt_on_close(fig, job)  # Interrupts the job when closing the figure

    while results.is_processing():
        # Fetch results, specifically the latest counts1 value
        counts, counts1, counts_dark1, iteration = results.fetch_all()

        # Progress bar
        progress_counter(iteration, n_avg, start_time=results.get_start_time())
        # Plot data
        plt.cla()
        #Plot raw counts
        plt.plot(4 * t_vec, counts1 / counts_dark1, label="x90_idle_x90")
        #plt.plot(4 * t_vec, counts2 / counts_dark2, label="x90_idle_-x90")
        #plt.plot(4 * t_vec, counts_dark / 1000 / (meas_len_1 / u.s), label="dark counts")
        #Plot counts normalised against dark counts
        #plt.plot(4 * t_vec, y90 / 1000 / (meas_len_1 / u.s), label="x90_idle_x90")
        #plt.plot(4 * t_vec, yminus90 / 1000 / (meas_len_1 / u.s), label="x90_idle_-x90")
        plt.xlabel("Ramsey idle time [ns]")
        plt.ylabel("Intensity [kcps]")
        plt.title("Ramsey")
        plt.legend()
        plt.pause(0.1)
        print(f"n: {iteration}", f"counts: {counts[0]}")

save_data = True
if save_data:
    data_to_csv = np.array([t_vec * 4, counts1 / counts_dark1, counts2 / counts_dark2]).transpose()
    np.savetxt('last_run_data_T1.csv', data_to_csv, delimiter=',')

