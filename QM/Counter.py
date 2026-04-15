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
from experiment_base import ExperimentBase

settings = QSettings("Diamond", "QM_Counter")
class SettingsDialogRabi(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.load_settings()
        self.setWindowTitle("Settings")

        buttons = (
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )

        button_box = QDialogButtonBox(buttons)
        button_box.accepted.connect(self.accept)  # type: ignore
        button_box.rejected.connect(self.reject)  # type: ignore

        # Main layout
        layout = QVBoxLayout()

        layout.addWidget(button_box)
        self.setLayout(layout)

    def load_settings(self):
        """Load saved settings and update widgets."""
    def accept(self):
        """Override accept to save settings when OK button is clicked."""
        super().accept()

    @staticmethod
    def get_settings():
        """Retrieve settings from QSettings. Returns tuple of (freq, time_max, num_points, n_avg)"""

class Counter(ExperimentBase):
    def __init__(self):

        self.qmm = QuantumMachinesManager(host=qop_ip, cluster_name=cluster_name,
                                          octave_calibration_db_path=calibration_db_dir)
        self.qm = self.qmm.open_qm(config, close_other_machines=True)
        self.is_running = False
        self.counter = None
        self.job = None

        # Data storage for GUI integration
        self.time_data = []
        self.counts_data = []
        self.rolling_avg_data = []

    def round_to_1(x):
        if x != 0:
            return round(x, -int(floor(log10(abs(x)))))
        else:
            return 0

    def compile_program(self):
        ##################
        #   Parameters   #
        ##################
        # Parameters Definition
        n_count = 3000
        meas_len = meas_len_1

        ###################
        # The QUA program #
        ###################
        with program() as self.counter:
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

    def get_x(self):
        """Return time data in seconds"""
        return np.array(self.time_data) if len(self.time_data) > 0 else np.array([])

    def get_y(self):
        """Return counts data in kcps"""
        return np.array(self.counts_data) if len(self.counts_data) > 0 else np.array([])

    def stop_program(self):
        self.is_running = False
        try:
            self.job.halt()
        except Exception as e:
            print(f"Error halting the job: {e}")
    simulate = False

    def save_data(self):
        pass

    def fit(self) -> tuple:
        """Return rolling average as the fitted curve for Counter with statistics"""
        if len(self.time_data) > 0 and len(self.rolling_avg_data) > 0:
            # Calculate statistics
            avg_counts = np.mean(self.counts_data[-20:]) if len(self.counts_data) >= 20 else np.mean(self.counts_data)

            # Format the average with appropriate units
            if avg_counts >= 1000:
                unit = "Mcps"
                display_avg = avg_counts / 1000
            elif avg_counts < 1:
                unit = "cps"
                display_avg = avg_counts * 1000
            else:
                unit = "kcps"
                display_avg = avg_counts

            fit_text = f"Rolling Average (10-point window)\nAverage Counts: {display_avg:.2f} {unit}"

            return np.array(self.time_data), np.array(self.rolling_avg_data), fit_text
        else:
            return np.array([]), np.array([]), ""

    def get_plot_info(self):
        return {
            "x_text": "Time",
            "x_units": "s",
            "y_text": "Counts",
            "y_units": "kcps",
        }

    def start_program(self):
        # Always recompile to apply any setting changes
        self.compile_program()
        simulate = False
        if simulate:
            # Simulates the QUA program for the specified duration
            simulation_config = SimulationConfig(duration=10_000)  # In clock cycles = 4ns
            # Simulate blocks python until the simulation is done
            job = self.qmm.simulate(config, self.counter, simulation_config)
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
            self.job = self.qm.execute(self.counter)
            # Get results from QUA program
            res_handles = self.job.result_handles
            counts_handle = res_handles.get("counts")
            counts_handle.wait_for_values(5)
            self.time_data = []
            self.counts_data = []
            self.rolling_avg_data = []
            points = 1000
            last_idx = 0

            while res_handles.is_processing() and self.is_running:
                new_idx = counts_handle.count_so_far()
                new_counts = counts_handle.fetch(slice(last_idx, new_idx))
                last_idx = new_idx

                self.time_data.extend(new_counts["timestamp"] / 1E9)  # Convert timestamps to seconds
                self.counts_data.extend(new_counts["value"] / (meas_len_1*1E-9*3000) / 1000) # Convert counts to kcps

                # Limit data points displayed
                if len(self.time_data) > points:
                    self.counts_data = self.counts_data[-points:]
                    self.time_data = self.time_data[-points:]

                # Calculate rolling average
                self.rolling_avg_data = [sum(self.counts_data[max(0, i-9):i+1]) / min(10, i+1) for i in range(len(self.counts_data))]

                time.sleep(0.01)  # Small delay to prevent blocking
