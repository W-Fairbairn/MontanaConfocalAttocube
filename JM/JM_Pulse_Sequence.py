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

# The time vector for varying the idle time in clock cycles (4ns)
t_vec = np.arange(0, 125000, 6250) # This does not appear to be in clock cycles. In the OPX+ simulation, the pulse length increases in increments of 6250 ns.
n_avg = 1_000_000

with program() as hahn_echo:
    counts1 = declare(int)  # saves number of photon counts
    counts2 = declare(int)  # saves number of photon counts
    counts_dark = declare(int)  # saves number of photon counts
    times1 = declare(int, size=100)  # QUA vector for storing the time-tags
    times2 = declare(int, size=100)  # QUA vector for storing the time-tags
    times_dark = declare(int, size=100)  # QUA vector for storing the time-tags
    t = declare(int)  # variable to sweep over in time
    n = declare(int)  # variable to for_loop
    b = declare(int)  # variable for refocusing loop
    counts_1_st = declare_stream()  # stream for counts
    counts_2_st = declare_stream()  # stream for counts
    counts_dark_st = declare_stream()  # stream for counts
    n_st = declare_stream()  # stream to save iterations

    # Spin initialization
    play("laser_ON", "AOM1")
    wait(wait_between_runs * u.ns, "AOM1")

    # Hahn echo sequence
    with for_(n, 0, n < n_avg, n + 1):
        with for_(*from_array(t, t_vec)):
            # Readout in bright state.
            a = declare(int)
            assign(a, 0)
            play("x90" * amp(1), "NV")
            #wait(10, "NV")  # Variable idle time
            play("y90/5" * amp(1), "NV")
            #wait(10, "NV")
            with while_(a < t):
                play("-y90/2.5" * amp(1), "NV")
                #wait(10, "NV")
                play("y90/2.5" * amp(1), "NV")
                assign(a, a + pi_half_len_NV/1.25)
            #wait(10, "NV")
            play("-y90/5" * amp(1), "NV")
            #wait(10, "NV")
            play("x90" * amp(1), "NV")

            align()  # Play the laser pulse after the sequence
            # Measure and detect the photons on SPCM1

            play("laser_ON", "AOM1")
            measure("readout", "SPCM1", None, time_tagging.analog(times1, meas_len_1, counts1))
            save(counts1, counts_1_st)  # save counts
            wait(wait_between_runs * u.ns, "AOM1")

            align()
            # Readout in dark state.
            a = declare(int)
            assign(a, 0)
            play("x90" * amp(1), "NV")
            # wait(10, "NV")  # Variable idle time
            play("y90/5" * amp(1), "NV")
            # wait(10, "NV")
            with while_(a < t):
                play("-y90/2.5" * amp(1), "NV")
                # wait(10, "NV")
                play("y90/2.5" * amp(1), "NV")
                assign(a, a + pi_half_len_NV/1.25)
            # wait(10, "NV")
            play("-y90/5" * amp(1), "NV")
            # wait(10, "NV")
            play("-x90" * amp(1), "NV")
            align()
            play("laser_ON", "AOM1")
            measure("readout", "SPCM1", None, time_tagging.analog(times2, meas_len_1, counts2))
            save(counts2, counts_2_st)  # save counts
            wait(wait_between_runs * u.ns, "AOM1")

            align()
            # Measuring the dark counts.
            a = declare(int)
            assign(a, 0)
            play("x90" * amp(0), "NV")
            # wait(10, "NV")  # Variable idle time
            play("y90/5" * amp(0), "NV")
            # wait(10, "NV")
            with while_(a < t):
                play("-y90/2.5" * amp(0), "NV")
                # wait(10, "NV")
                play("y90/2.5" * amp(0), "NV")
                assign(a, a + pi_half_len_NV/1.25)
            # wait(10, "NV")
            play("-y90/5" * amp(0), "NV")
            # wait(10, "NV")
            play("-x90" * amp(0), "NV")
            # Measure and detect the dark counts on SPCM1
            align()
            play("laser_ON", "AOM1")
            measure("readout", "SPCM1", None, time_tagging.analog(times_dark, meas_len_1, counts_dark))
            save(counts_dark, counts_dark_st)  # save counts
            wait(wait_between_runs * u.ns, "AOM1")

        save(n, n_st)  # save number of iteration inside for_loop
        with if_(n > 0):
            with if_(n - (46728 * (n / 46728)) == 0):
                with for_(b, 0, b < 100, b + 1):
                    play("laser_ON_refocusing", "AOM1")


    with stream_processing():
        # Cast the data into a 1D vector, average the 1D vectors together and store the results on the OPX processor
        counts_1_st.buffer(len(t_vec)).average().save("counts1")
        counts_2_st.buffer(len(t_vec)).average().save("counts2")
        counts_dark_st.buffer(len(t_vec)).average().save("counts_dark")
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
    simulation_config = SimulationConfig(duration=1_000_000)  # In clock cycles = 4ns
    job = qmm.simulate(config, hahn_echo, simulation_config)
    job.get_simulated_samples().con1.plot()
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
            qm.calibrate_element(element, {NV_LO_freq: (NV_IF_freq,)})  # can provide many IFs for specific LO
    # Send the QUA program to the OPX, which compiles and executes it
    # execute QUA program
    job = qm.execute(hahn_echo)
    # Get results from QUA program
    results = fetching_tool(job, data_list=["counts1", "counts2", "counts_dark", "iteration"], mode="live")
    # Live plotting
    fig = plt.figure()
    interrupt_on_close(fig, job)  # Interrupts the job when closing the figure
    #job.result_handles.save_to_store(None, False)

    while results.is_processing():
        # Fetch results
        counts1, counts2, counts_dark, iteration = results.fetch_all()
        # Progress bar
        progress_counter(iteration, n_avg, start_time=results.get_start_time())
        # Plot data
        plt.cla()
        plt.plot(t_vec, counts1 / 1000 / (meas_len_1 / u.s), label="x90_idle_x180_idle_x90")
        plt.plot(t_vec, counts2 / 1000 / (meas_len_1 / u.s), label="x90_idle_x180_idle_-x90")
        plt.plot(t_vec, counts_dark / 1000 / (meas_len_1 / u.s), label="dark counts")
        plt.xlabel("Idle time [ns]")
        plt.ylabel("Intensity [kcps]")
        plt.title("Hahn Echo")
        plt.legend()
        plt.pause(0.1)
        print(iteration)

