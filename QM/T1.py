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

#from configuration import *
from qualang_tools.loops import from_array
from qualang_tools.results.data_handler import DataHandler
import numpy as np
from pathlib import Path
import threading
from multiprocessing.connection import Listener
import sys
import signal
import time
from scipy.optimize import curve_fit
from PyQt6 import QtCore, QtWidgets, QtGui, uic
from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QColor, QAction
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QRadioButton,
    QVBoxLayout,
    QLabel,
    QLineEdit,
)
from experiment_base import *
from settings_dialog_base import SettingsDialogBase

settings = QSettings("Diamond", "QM_T1")


class SettingsDialogT1(SettingsDialogBase):
    SETTINGS_GROUP = "QM_T1"
    WINDOW_TITLE = "Settings"

    SETTINGS_SCHEMA = {
        "time_max": {"label": "Time max (ns):", "default": 500, "type": int},
        "num_points": {"label": "Number of points:", "default": 50, "type": int},
        "num_averages": {"label": "Number of averages:", "default": 10_000_000, "type": int},
    }


class T1(ExperimentBase):
    def __init__(self):

        self.conn = None
        self.qmm = None
        self.qm = None
        ##################
        #   Parameters   #
        ##################
        self.t_vec = None
        self.length_run, self.num_points, self.n_avg = None, None, None
        self.is_running = False
        self.T1 = None
        self.time_tag_arr = []
        self.counts, self.counts_ref, self.iteration = None, None, None
        # Data to save
        self.save_data_dict = {
            "n_avg": self.n_avg,
            "t_vec": self.t_vec,
            "config": config,
        }

    def compile_program(self):
        self.time_tag_arr = []

        s = SettingsDialogT1.get_settings()
        self.length_run = int(s["time_max"])
        self.num_points = int(s["num_points"])
        self.n_avg = int(s["num_averages"])

        self.t_vec = np.arange(400, self.length_run // 4, max(1, self.length_run // (4 * self.num_points)))
        time_arr_len = 1000

        import time as time_module
        print("1")
        t1 = time_module.time()
        self.qmm = QuantumMachinesManager(host=qop_ip, cluster_name=cluster_name,
                                          octave_calibration_db_path=calibration_db_dir)
        print(f"2 (QuantumMachinesManager: {time_module.time() - t1:.2f}s)")
        t2 = time_module.time()
        self.qm = self.qmm.open_qm(config, close_other_machines=True)
        print(f"3 (open_qm: {time_module.time() - t2:.2f}s)")
        t3 = time_module.time()

        with program() as self.T1:
            counts = declare(int)  # saves number of photon counts
            counts_ref = declare(int)  # saves number of photon counts in reference readout
            times = declare(int, size=time_arr_len)  # QUA vector for storing the time-tags
            times_ref = declare(int, size=time_arr_len)  # QUA vector for storing the time-tags of reference counts
            times_st = declare_stream()  # stream to save time tags of counts, ref
            counts_st = declare_stream()  # stream for counts
            counts_ref_st = declare_stream()  # stream for reference counts
            n_st = declare_stream()  # stream to save iterations

            t = declare(int)  # variable to sweep over delay
            n = declare(int)  # variable to sweep over iterations
            i = declare(int)  # variable to sweep over time tags

            with for_(n, 0, n < self.n_avg, n + 1):
                with for_(*from_array(t, self.t_vec)):
                    align()
                    wait(t)                                      # wait the variable delay (in clock cycles)
                    align()
                    play("laser_ON", "AOM2")        # laser on for readout
                    measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
                    save(counts, counts_st)
                    measure("readout", "SPCM1", time_tagging.analog(times_ref, meas_len_1, counts_ref))
                    save(counts_ref, counts_ref_st)  # save ref counts

                    # noinspection PyTypeChecker
                    #with for_(i, 0, i < counts, i + 1):
                    #    save(times[i], times_st)  # cant directly save QUA vector, loop and save each element separately

                with while_(IO1):  # refocusing loop
                    play("laser_ON", "AOM2")  # laser on for optimise
                    wait(wait_for_initialization * u.ns, "AOM2")
                    align()

                save(n, n_st)  # save number of iteration inside for_loop

            with stream_processing():
                counts_st.buffer(len(self.t_vec)).average().save("counts")  # save average counts for each point in an array
                counts_ref_st.buffer(len(self.t_vec)).average().save("counts_ref")
                #times_st.buffer(time_arr_len).save("time_tags")  # save time tags buffer size should be larger than counts expected
                n_st.save("iteration")

                # save_all creates large buffer of data on OPX
                # if iterations and point count are too large may exceed memory limit (100E6 int)
                #counts_st.buffer(len(self.t_vec)).save_all("raw_counts")
                #counts_ref_st.buffer(len(self.t_vec)).save_all("raw_counts_ref")
        print(f"4 (program compilation: {time_module.time() - t3:.2f}s)")


    def receive_signal(self):
        print("Thread: Sleeping until signal received...")
        address = ("localhost", 6000)
        listener = Listener(address, authkey=b"secret password")
        print("connection accepted from", listener.last_accepted)
        while True:
            try:
                self.conn = listener.accept()
                msg = self.conn.recv()
                print(msg)
                if msg == "start":
                    self.qm.set_io1_value(True)
                    print("Paused")
                elif msg == "stop":
                    self.qm.set_io1_value(False)
                    print("Resumed")
                elif msg == "close":
                    self.conn.close()
                    break
            except Exception as ex:
                print(f"Error: {ex}")
                break

        listener.close()



    def get_x(self):
        return self.t_vec * 4 * 1e-9  # Convert to seconds

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
        finally:
            if self.conn:
                self.conn.close()

    def save_data(self):
        script_name = Path(__file__).name
        data_handler = DataHandler(root_data_folder='C:/Users/attocube/Documents/MontanaQudiAttocube/MontanaConfocalAttocube/QM/save_dir')
        self.save_data_dict.update({"counts_data": self.counts})
        self.save_data_dict.update({"t_vec": self.t_vec})
        self.save_data_dict.update({"iteration": np.array([int(self.iteration)])})
        #self.save_data_dict.update({"time_tag_arr": self.time_tag_arr})
        self.save_data_dict.update({"counts_ref": self.counts_ref})
        #self.save_data_dict.update({"raw_counts": np.array(self.raw_counts)})
        #self.save_data_dict.update({"raw_counts_ref": np.array(self.raw_counts_ref)})
        data_handler.save_data(data=self.save_data_dict, name=script_name.split(".")[0])

    def get_plot_info(self):
        return {
            "x_text": "Time",
            "x_units": "s",
            "y_text": "Normalised signal",
            "y_units": "arb. units",
        }

    def fit(self):
        x, y, err = self.get_x(), self.get_y(), self.get_err()

        def decay_func(t, A, T1, C):
            return A * np.exp(-t / T1) + C

        y_span = np.max(y) - np.min(y)
        A_guess = y_span if y_span > 0 else 1.0
        C_guess = np.min(y) if y_span > 0 else np.mean(y)
        T1_guess = max((np.max(x) - np.min(x)) / 2, 1e-12)

        if err is not None and (not np.all(np.isfinite(err)) or np.any(err <= 0)):
            err = None

        fit_kwargs = {"p0": (A_guess, T1_guess, C_guess), "maxfev": 5000}
        if err is not None:
            fit_kwargs["sigma"] = err
            fit_kwargs["absolute_sigma"] = True

        popt, pcov = curve_fit(decay_func, x, y, **fit_kwargs)
        A_fit, T1_fit, C_fit = popt
        perr = np.sqrt(np.diag(pcov))
        A_err, T1_err, C_err = perr
        interp_x = np.linspace(min(x), max(x), 500)
        fit_y = decay_func(interp_x, *popt)
        text = f'T1 = {T1_fit / 1E-6:.2f} ± {T1_err / 1E-6:.2f} us'
        return [interp_x, fit_y, text]

    def start_program(self):
        self.compile_program()
        simulate = False
        if simulate:
            # For debugging the waveform, it's often convenient to simulate a single iteration:
            #   n_avg = 1
            #   t_vec = np.array([some_short_delay_in_clock_cycles])
            # and reduce the duration accordingly.
            simulation_config = SimulationConfig(duration=3_000)  # In clock cycles = 4ns
            # Simulate blocks python until the simulation is done
            job = self.qmm.simulate(config, self.T1, simulation_config)
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
            # Open quantum machine and execute program
            self.qm.set_io1_value(False)  # Ensure IO1 is low at the start of the program (not paused)
            self.job = self.qm.execute(self.T1)  # start the job

            results = fetching_tool(
                self.job, data_list=["counts", "counts_ref", "iteration"], mode="live"
            )
            t2 = threading.Thread(target=self.receive_signal, daemon=True)  # Thread to receive pause/resume signals from external script
            t2.start()

            while results.is_processing():
                try:
                    # Fetch the latest data
                    self.counts, self.counts_ref, self.iteration = results.fetch_all()
                    time.sleep(0.1)  # Small delay to prevent excessive CPU usage
                except Exception as e:
                    print(f"Error fetching results: {e}")
                    break
