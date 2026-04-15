"""
        CW Optically Detected Magnetic Resonance (ODMR)
The program consists in playing a mw pulse and the readout laser pulse simultaneously to extract
the photon counts received by the SPCM across varying intermediate frequencies.

The data is then post-processed to determine the spin resonance frequency.
This frequency can be used to update the NV intermediate frequency in the configuration under "NV_IF_freq".

Prerequisites:
    - Ensure calibration of the different delays in the system (calibrate_delays).
    - Update the different delays in the configuration

Next steps before going to the next node:
    - Update the NV frequency, labeled as "NV_IF_freq", in the configuration.
"""

from qm import QuantumMachinesManager
from qm.qua import *
from qm import SimulationConfig
import matplotlib.pyplot as plt
from configuration import *
from qualang_tools.results.data_handler import DataHandler
from pathlib import Path
import time
import numpy as np
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
from experiment_base import ExperimentBase

settings = QSettings("Diamond", "QM_ODMR")


class SettingsDialogODMR(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.load_settings()
        self.setWindowTitle("Settings")

        self.readout_len = long_meas_len_1
        self.freq_min = QLineEdit(str(self.freq_min), parent=self)
        self.freq_max = QLineEdit(str(self.freq_max), parent=self)
        self.num_points = QLineEdit(str(self.num_points), parent=self)
        self.num_averages = QLineEdit(str(self.num_averages), parent=self)
        self.num_peaks = QLineEdit(str(self.num_peaks), parent=self)


        buttons = (
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )

        button_box = QDialogButtonBox(buttons)
        button_box.accepted.connect(self.accept)  # type: ignore
        button_box.rejected.connect(self.reject)  # type: ignore

        # Main layout
        layout = QVBoxLayout()

        layout.addWidget(QLabel("Freq min (ns):"))
        layout.addWidget(self.freq_max)
        layout.addWidget(QLabel("Freq max (ns):"))
        layout.addWidget(self.freq_max)
        layout.addWidget(QLabel("Number of points:"))
        layout.addWidget(self.num_points)
        layout.addWidget(QLabel("Number of averages:"))
        layout.addWidget(self.num_averages)

        layout.addWidget(QLabel(""))

        layout.addWidget(QLabel("Number of peaks to fit:"))
        layout.addWidget(self.num_peaks)

        layout.addWidget(button_box)
        self.setLayout(layout)

    def load_settings(self):
        """Load saved settings and update widgets."""
        self.freq_min = settings.value("freq_min", -150)
        self.freq_max = settings.value("freq_max", 150)
        self.num_points = settings.value("num_points", 100)
        self.num_averages = settings.value("num_averages", 10000000)
        self.num_peaks = settings.value("num_peaks", 1)

    def accept(self):
        """Override accept to save settings when OK button is clicked."""
        settings.setValue("freq_min", self.freq_min.text())
        settings.setValue("freq_max", self.freq_max.text())
        settings.setValue("num_points", self.num_points.text())
        settings.setValue("num_averages", self.num_averages.text())
        settings.setValue("num_peaks", self.num_peaks.text())
        super().accept()

    @staticmethod
    def get_settings():
        """Retrieve settings from QSettings. Returns tuple of (freq, time_max, num_points, n_avg, num_peaks)"""
        try:
            freq_min = float(settings.value("freq_min", -150))
            freq_max = float(settings.value("freq_max", 150))
            num_points = int(settings.value("num_points", 100))
            n_avg = int(settings.value("num_averages", 10000000))
            num_peaks = int(settings.value("num_peaks", 1))
            return freq_min, freq_max, num_points, n_avg, num_peaks
        except (ValueError, TypeError):
            print("Invalid Inputs, using default values.")
            return -150, 150, 100, 10000000, 1


class CW_ODMR(ExperimentBase):
    def __init__(self):

        self.qmm = QuantumMachinesManager(host=qop_ip, cluster_name=cluster_name,
                                          octave_calibration_db_path=calibration_db_dir)
        self.qm = self.qmm.open_qm(config, close_other_machines=True)
        self.job = None
        ##################
        #   Parameters   #
        ##################
        self.is_running = False
        self.num_points = None
        self.length_run = None
        self.f_vec = None
        self.f_vec_float = None
        self.n_avg = None
        self.num_peaks = 1
        self.cw_odmr = None
        self.counts, self.counts_ref, self.iteration, self.time_tags = None, None, None, None
        self.readout_len = long_meas_len_1
        self.original_rf_gain = None
        # Data to save
        self.save_data_dict = {
            "n_avg": self.n_avg,
            "f_vec": self.f_vec,
            "config": config,
        }

    def compile_program(self):
        # Clear data arrays from previous runs
        self.counts, self.counts_ref, self.iteration, self.time_tags = None, None, None, None
        freq_min, freq_max, self.num_points, self.n_avg, self.num_peaks = SettingsDialogODMR.get_settings()
        try:
            self.f_vec = np.arange(freq_min * u.MHz, freq_max * u.MHz, max((freq_max-freq_min)/self.num_points, 1) * u.MHz)
        except Exception as e:
            print(f"Error creating frequency vector: {e}")
            self.f_vec = np.arange(-150 * u.MHz, 150 * u.MHz, 2 * u.MHz)  # Default frequency vector

        # Save original gain value to restore later
        self.original_rf_gain = config["octaves"][octave]["RF_outputs"][1]["gain"]
        # Set the gain for RF output 1 to -15 dB due to cw delivering high power compared to pulsed
        config["octaves"][octave]["RF_outputs"][1]["gain"] = -20
        ###################
        # The QUA program #
        ###################
        with program() as self.cw_odmr:
            times = declare(int, size=100)  # QUA vector for storing the time-tags
            counts = declare(int)  # variable for number of counts
            counts_st = declare_stream()  # stream for counts
            f = declare(int)  # frequencies
            n = declare(int)  # number of iterations
            n_st = declare_stream()  # stream for number of iterations

            with for_(n, 0, n < self.n_avg, n + 1):
                with for_(*from_array(f, self.f_vec)):
                    # Update the frequency of the digital oscillator linked to the element "NV"
                    update_frequency("NV", f)
                    # align all elements before starting the sequence
                    align()
                    # Play the mw pulse...
                    play("cw" * amp(1), "NV", duration=self.readout_len * u.ns)
                    # ... and the laser pulse simultaneously (the laser pulse is delayed by 'laser_delay_1')
                    play("laser_ON", "AOM2", duration=self.readout_len * u.ns)
                    wait(1_000 * u.ns, "SPCM1")  # so readout don't catch the first part of spin reinitialization
                    # Measure and detect the photons on SPCM1

                    measure("long_readout", "SPCM1", time_tagging.analog(times, self.readout_len, counts))

                    save(counts, counts_st)  # save counts on stream

                    wait(wait_between_runs * u.ns)

                    save(n, n_st)  # save number of iteration inside for_loop

            with stream_processing():
                # Cast the data into a 1D vector, average the 1D vectors together and store the results on the OPX processor
                counts_st.buffer(len(self.f_vec)).average().save("counts")
                n_st.save("iteration")

    def get_x(self):
        if self.f_vec is not None:
            return (NV_LO_freq + self.f_vec) / u.GHz  # Convert to GHz
        else:
            return np.array([])

    def get_y(self):
        if self.counts is not None:
            return self.counts / 1000 / (self.readout_len * 1e-9)
        else:
            return np.zeros(len(self.f_vec))

    def stop_program(self):
        self.is_running = False
        try:
            self.job.halt()
        except Exception as e:
            print(f"Error halting the job: {e}")
        finally:
            # Restore the original config when stopping
            self.restore_config()

    def save_data(self):
        # Save results
        script_name = Path(__file__).name
        data_handler = DataHandler(root_data_folder=save_dir)
        self.save_data_dict.update({"counts_data": self.counts})
        self.save_data_dict.update({"freq_data": self.f_vec})
        # data_handler.additional_files = {script_name: script_name, **default_additional_files}
        data_handler.save_data(data=self.save_data_dict, name=script_name.split(".")[0])

    def get_plot_info(self):
        return {
            "x_text": "MW frequency",
            "x_units": "GHz",
            "y_text": "Counts",
            "y_units": "kcps",
        }

    def fit(self):
        """Fit the ODMR data with multiple Lorentzian dips"""
        x = self.get_x()
        y = self.get_y()

        if x is None or y is None or len(x) == 0 or len(y) == 0:
            return None, None, "No data available for fitting"

        # Define the fitting function for multiple Lorentzian dips
        def multi_lorentzian(f, *params):
            """
            Multiple Lorentzian dip function.
            Each peak has 3 parameters: f0 (frequency), A (amplitude), gamma (linewidth)
            """
            result = np.zeros_like(f, dtype=float)

            # Sum contributions from each Lorentzian dip
            for i in range(self.num_peaks):
                f0 = params[3*i]        # Center frequency of peak i
                A = params[3*i + 1]     # Amplitude of peak i
                gamma = params[3*i + 2] # Linewidth of peak i

                # Add Lorentzian dip to result
                result += A * (gamma**2 / ((f - f0) ** 2 + gamma**2))

            return result

        try:
            # Create initial guesses for the parameters
            p0 = []
            y_min = np.min(y)
            y_max = np.max(y)
            amp_guess = (y_max - y_min) / 2

            for i in range(self.num_peaks):
                # Find approximate peaks by dividing the frequency range
                idx = i * len(x) // self.num_peaks
                f0_guess = x[idx]
                A_guess = amp_guess
                gamma_guess = (np.max(x) - np.min(x)) / (4 * self.num_peaks)

                p0.extend([f0_guess, A_guess, gamma_guess])

            # Perform the fit
            popt, _ = curve_fit(multi_lorentzian, x, y, p0=p0, maxfev=5000)

            # Generate high-resolution fit curve for plotting
            x_fit = np.linspace(np.min(x), np.max(x), 1000)
            y_fit = multi_lorentzian(x_fit, *popt)

            # Build results text
            text = "ODMR Fit Results:\n"
            text += f"Number of peaks: {self.num_peaks}\n\n"
            for i in range(self.num_peaks):
                f0 = popt[3*i]
                A = popt[3*i + 1]
                gamma = popt[3*i + 2]
                text += f"Peak {i+1}:\n"
                text += f"  f0 = {f0:.4f} GHz\n"
                text += f"  Amplitude = {A:.4e}\n"
                text += f"  Linewidth (γ) = {gamma:.4f} GHz\n\n"

            return x_fit, y_fit, text

        except Exception as e:
            return None, None, f"Fit failed: {str(e)}"

    def restore_config(self):
        """Restore the original RF output gain from before compilation"""
        if hasattr(self, 'original_rf_gain'):
            config["octaves"][octave]["RF_outputs"][1]["gain"] = self.original_rf_gain

    def start_program(self):
        # Always recompile to apply any setting changes
        self.compile_program()
        simulate = False

        if simulate:
            # Simulates the QUA program for the specified duration
            simulation_config = SimulationConfig(duration=10_000)  # In clock cycles = 4ns
            # Simulate blocks python until the simulation is done
            job = self.qmm.simulate(config, self.cw_odmr, simulation_config)
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
            try:
                self.job = self.qm.execute(self.cw_odmr)
                results = fetching_tool(self.job, data_list=["counts", "iteration"], mode="live")
                while results.is_processing():
                    self.counts, self.iteration = results.fetch_all()
                    time.sleep(0.01)
                self.save_data()
            finally:
                # Always restore the original config, even if an error occurs
                self.restore_config()

