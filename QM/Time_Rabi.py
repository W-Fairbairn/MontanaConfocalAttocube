"""
        TIME RABI
The program consists in playing a mw pulse and measure the photon counts received by the SPCM
across varying mw pulse durations.
The sequence has a reference measurement window at the end of the laser pulse to normalize the photon counts.

The data is then post-processed to determine the pi pulse duration for the specified amplitude.

Prerequisites:
    - Ensure calibration of the different delays in the system (calibrate_delays).
    - Having updated the different delays in the configuration.
    - Having updated the NV frequency, labeled as "NV_IF_freq", in the configuration.
    - Set the desired pi pulse amplitude, labeled as "mw_amp_NV", in the configuration

Next steps before going to the next node:
    - Update the pi pulse duration, labeled as "mw_len_NV", in the configuration.
"""
import numpy as np
from qm import QuantumMachinesManager
from qm.qua import *
from qm import SimulationConfig
import matplotlib.pyplot as plt
from configuration import *
from qualang_tools.results.data_handler import DataHandler
import time
from scipy.optimize import curve_fit
class Rabi():
    def __init__(self):

        self.qmm = QuantumMachinesManager(host=qop_ip, cluster_name=cluster_name,
                                          octave_calibration_db_path=calibration_db_dir)
        self.qm = self.qmm.open_qm(config, close_other_machines=True)

        ##################
        #   Parameters   #
        ##################
        self.is_running = False
        self.last_counts = None
        self.last_counts_ref = None
        self.last_iteration = None
        self.num_points = 50
        self.length_run = 500
        self.t_vec = np.arange(4, self.length_run//4, max(1,self.length_run//(4*self.num_points)))  # Pulse durations in clock cycles (4ns)
        self.n_avg = 10_000_000  # Number of averaging loops


        # Determine reference readout during single laser pulse
        self.reference_wait = initialization_len_2 // 4 - AOM_delay - 2 * meas_len_1 // 4 - 100  # in clock cycles
        self.reference_readout = self.reference_wait >= 4

        self.ref_offset = (initialization_len_2 - 2 * meas_len_1 - 25 - AOM_delay) // 4

        # Data to save
        self.save_data_dict = {
            "n_avg": self.n_avg,
            "t_vec": self.t_vec,
            "config": config,
        }

        self.counts, self.counts_ref, self.iteration, self.time_tags = None, None, None, None

        ###################
        # The QUA program #
        ###################
        with program() as self.time_rabi:
            counts = declare(int)  # variable for number of counts
            counts_ref = declare(int)  # variable for number of counts in reference window
            counts_st = declare_stream()  # stream for counts
            counts_ref_st = declare_stream()  # stream for counts
            times = declare(int, size=1000)  # QUA vector for storing the time-tags
            times_ref = declare(int, size=1000)  # QUA vector for storing the time-tags
            t = declare(int)  # variable to sweep over in time
            i = declare(int)  # variable to sweep over
            n = declare(int)  # variable to for_loop
            n_st = declare_stream()  # stream to save iterations
            times_st = declare_stream()

            # Spin initialization
            play("laser_ON", "AOM2")
            wait(wait_for_initialization)  # Wait for spin to return to ground state
            align()  # Ensure initialization is complete before starting Rabi

            # Time Rabi sweep
            with for_(n, 0, n < self.n_avg, n + 1):
                with for_(*from_array(t, self.t_vec)):
                    update_frequency("NV", 100 * u.MHz)
                    play("x180" * amp(1), "NV", duration=t)
                    align()  # Play the laser pulse after the mw pulse
                    #wait(AOM_delay, "SPCM1")
                    play("laser_ON", "AOM2")
                    measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
                    save(counts, counts_st)  # save counts
                    with for_(i, 0, i < counts, i + 1):
                        save(times[i], times_st)  # cant directly save QUA vector, loop and save each element separately
                    #wait(800//4, "SPCM1")
                    measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
                    save(counts, counts_ref_st)
                    wait(wait_between_runs * u.ns)

                save(n, n_st)  # save number of iteration inside for_loop

            with stream_processing():
                # Cast the data into a 1D vector, average the 1D vectors together and store the results on the OPX processor
                counts_st.buffer(len(self.t_vec)).average().save("counts")
                counts_ref_st.buffer(len(self.t_vec)).average().save("counts_ref")
                times_st.buffer(1000).save("time_tags")
                n_st.save("iteration")

    def get_x(self):
        return self.t_vec * 4  # Convert to ns

    def get_y(self):
        if self.counts is not None and self.counts_ref is not None:
            return self.counts / self.counts_ref
        else:
            return np.zeros(len(self.t_vec))
    def get_err(self):
        if self.counts is not None and self.counts_ref is not None and self.iteration is not None:
            count_err = np.sqrt(self.counts * self.iteration) / self.iteration
            ref_err = np.sqrt(self.counts_ref * self.iteration) / self.iteration
            norm_err = (self.counts / self.counts_ref) * np.sqrt((count_err / self.counts) ** 2 + (ref_err / self.counts_ref) ** 2)
            return norm_err
        else:
            return None

    def stop_program(self):
        self.is_running = False
        try:
            self.job.halt()
        except Exception as e:
            print(f"Error halting the job: {e}")

    def save_data(self):
        # Save results
        script_name = Path(__file__).name
        data_handler = DataHandler(root_data_folder=save_dir)
        self.save_data_dict.update({"counts_data": self.counts})
        self.save_data_dict.update({"counts_dark_data": self.counts_ref})
        self.save_data_dict.update({"normalized_data": self.counts / self.counts_ref})
        self.save_data_dict.update({"iteration": np.array([int(self.iteration)])})
        data_handler.save_data(data=self.save_data_dict, name="_".join(script_name.split("_")[1:]).split(".")[0])

    def fit_func(self, t, A, f, T2, phi, C):
        t = t * 1E-9  # Convert to seconds for fitting
        return A * np.exp(-t / T2) * np.sin(2 * np.pi * f * t + phi) + C

    def fit(self):
        x = self.get_x()
        y = self.get_y()
        err = self.get_err()
        A_guess = (np.max(y) - np.min(y)) / 2
        C_guess = np.mean(y)
        f_guess = 7E6  # Initial frequency guess in MHz
        T2_guess = 0.5E-6  # Decay time guess
        phi_guess = np.pi / 2  # Phase guess

        p0 = [A_guess, f_guess, T2_guess, phi_guess, C_guess]
        popt, pcov = curve_fit(self.fit_func, x, y, p0=p0, sigma=err, absolute_sigma=True, maxfev=5000)
        A_fit, f_fit, T2_fit, phi_fit, C_fit = popt
        perr = np.sqrt(np.diag(pcov))
        A_err, f_err, T2_err, phi_err, C_err = perr
        interp_x = np.linspace(min(x), max(x), 500)
        fit_y = self.fit_func(interp_x, *popt)
        text = f'T2 = {T2_fit / 1E-6:.2f} ± {T2_err / 1E-6:.2f} us,\nf = {f_fit / 1E6:.2f} ± {f_err / 1E6:.2f} MHz'
        return [interp_x, fit_y, text]

    def start_program(self):
        try:
            simulate = False
            if simulate:
                # Simulates the QUA program for the specified duration
                simulation_config = SimulationConfig(duration=10_000)  # In clock cycles = 4ns
                # Simulate blocks python until the simulation is done
                job = self.qmm.simulate(config, self.time_rabi, simulation_config)
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
                self.is_running = True
                self.job = self.qm.execute(self.time_rabi)
                results = fetching_tool(self.job, data_list=["counts", "counts_ref", "iteration", "time_tags"], mode="live")
                while results.is_processing():
                    self.counts, self.counts_ref, self.iteration, self.time_tags = results.fetch_all()
                    #print("counts:", self.counts)
                    time.sleep(0.01)  # Small sleep to prevent CPU spinning
                self.save_data(self.counts, self.counts_ref, self.iteration)
        except Exception as e:
            print(f"Error in start_rabi: {e}")
            import traceback
            traceback.print_exc()






'''
#####################################
#  Open Communication with the QOP  #
#####################################
qmm = QuantumMachinesManager(host=qop_ip, cluster_name=cluster_name, octave_calibration_db_path=calibration_db_dir)

#######################
# Simulate or execute #
#######################
simulate = False

if simulate:
    # Simulates the QUA program for the specified duration
    simulation_config = SimulationConfig(duration=10_000)  # In clock cycles = 4ns
    # Simulate blocks python until the simulation is done
    job = qmm.simulate(config, time_rabi, simulation_config)
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
    # Open the quantum machine
    qm = qmm.open_qm(config, close_other_machines=True)
    # Send the QUA program to the OPX, which compiles and executes it
    job = qm.execute(time_rabi)
    # Get results from QUA program
    results = fetching_tool(job, data_list=["counts", "counts_ref", "iteration", "time_tags"], mode="live")
    # Live plotting
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 8))
    interrupt_on_close(fig, job)  # Interrupts the job when closing the figure
    time_tag_arr = np.zeros(meas_len_1)

    while results.is_processing():
        # Fetch results
        counts, counts_ref, iteration, time_tags = results.fetch_all()
        # Progress bar
        progress_counter(iteration, n_avg, start_time=results.get_start_time())
        # Plot data
        ax1.cla()
        #ax1.plot(t_vec * 4, counts_ref, label="norm. photon counts")
        ax1.scatter(t_vec * 4, counts/counts_ref, label="counts")
        #ax1.xlabel("Rabi pulse duration [ns]")
        #ax1.ylabel("Counts")


        ax2.cla()
        for i in time_tags:
            time_tag_arr[i] += 1  # Convert histogram of time tags to array for faster plotting, saving memory
        time_tags = []
        ax2.plot(np.linspace(0, meas_len_1, meas_len_1), time_tag_arr[:])

        #plt.legend()
        plt.pause(0.1)
    # Save results
    script_name = Path(__file__).name
    data_handler = DataHandler(root_data_folder=save_dir)
    save_data_dict.update({"counts_data": counts})
    save_data_dict.update({"counts_dark_data": counts_ref})
    save_data_dict.update({"normalized_data": counts / counts_ref})
    save_data_dict.update({"iteration": np.array([int(iteration)])})
    save_data_dict.update({"fig_live": fig})
    data_handler.additional_files = {script_name: script_name, **default_additional_files}
    data_handler.save_data(data=save_data_dict, name="_".join(script_name.split("_")[1:]).split(".")[0])
'''