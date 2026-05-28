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
from scipy.signal import find_peaks
from PyQt6 import QtCore, QtWidgets, QtGui, uic
from PyQt6.QtCore import QSettings
from experiment_base import ExperimentBase
from settings_dialog_base import SettingsDialogBase


class SettingsDialogODMR(SettingsDialogBase):
    SETTINGS_GROUP = "QM_ODMR"
    WINDOW_TITLE = "Settings"

    # Single source of truth for editable settings
    SETTINGS_SCHEMA = {
        "freq_min": {"label": "Freq min (MHz):", "default": -150.0, "type": float},
        "freq_max": {"label": "Freq max (MHz):", "default": 150.0, "type": float},
        "num_points": {"label": "Number of points:", "default": 100, "type": int},
        "num_averages": {"label": "Number of averages:", "default": 10_000_000, "type": int, "spacer_after": True},
        "num_peaks": {"label": "Number of peaks to fit:", "default": 1, "type": int},
    }


class CW_ODMR(ExperimentBase):
    def __init__(self):
        self.qmm = None
        self.qm = None
        self.job = None
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
        self.cw_rf_gain_db = -15
        # Data to save
        self.save_data_dict = {
            "n_avg": self.n_avg,
            "f_vec": self.f_vec,
            "config": config,
        }

    def compile_program(self):
        # Clear data arrays from previous runs
        self.counts, self.counts_ref, self.iteration, self.time_tags = None, None, None, None

        s = SettingsDialogODMR.get_settings()
        freq_min = float(s["freq_min"])
        freq_max = float(s["freq_max"])
        self.num_points = int(s["num_points"])
        self.n_avg = int(s["num_averages"])
        self.num_peaks = int(s["num_peaks"])

        try:
            self.f_vec = np.arange(freq_min * u.MHz, freq_max * u.MHz, max((freq_max-freq_min)/self.num_points, 1) * u.MHz)
        except Exception as e:
            print(f"Error creating frequency vector: {e}")
            self.f_vec = np.arange(-150 * u.MHz, 150 * u.MHz, 2 * u.MHz)  # Default frequency vector

        # Save original gain value to restore later
        self.original_rf_gain = config["octaves"][octave]["RF_outputs"][1]["gain"]
        # Set the gain for RF output 1 to -15 dB due to cw delivering high power compared to pulsed
        config["octaves"][octave]["RF_outputs"][1]["gain"] = self.cw_rf_gain_db
        config["octaves"][octave]["RF_outputs"][1]["output_mode"] = 'always_on'
        self.qmm = QuantumMachinesManager(host=qop_ip, cluster_name=cluster_name,
                                          octave_calibration_db_path=calibration_db_dir)
        self.qm = self.qmm.open_qm(config, close_other_machines=True)
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
            return (NV_LO_freq + self.f_vec)  # Convert to GHz
        else:
            return np.array([])

    def get_y(self):
        if self.counts is not None:
            return self.counts / (self.readout_len * 1e-9)
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
            "x_units": "Hz",
            "y_text": "Counts",
            "y_units": "cps",
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
            for i in range(len(params)//3):
                f0 = params[3*i]        # Center frequency of peak i
                A = params[3*i + 1]     # Amplitude of peak i
                gamma = params[3*i + 2] # Linewidth of peak i

                # Add Lorentzian dip to result
                result += A * (gamma**2 / ((f - f0) ** 2 + gamma**2))

            return result

        try:
            # Convert to arrays
            x = np.asarray(x, dtype=float)
            y = np.asarray(y, dtype=float)
            self.num_peaks = int(SettingsDialogODMR.get("num_peaks", 1))
            # --- Peak finding for ODMR dips ---
            # ODMR shows dips in y. Work on an inverted, baseline-corrected, lightly smoothed trace.
            y0 = y - np.median(y)

            # Light smoothing to suppress point-to-point noise (moving average).
            # Keep it small so we don't wash out narrow resonances.
            win = max(3, (len(y0) // 200) | 1)  # odd window, ~0.5% of points
            if win > 3:
                kernel = np.ones(win, dtype=float) / win
                y_s = np.convolve(y0, kernel, mode="same")
            else:
                y_s = y0

            inv = -y_s

            inv_range = float(np.nanmax(inv) - np.nanmin(inv)) if len(inv) else 0.0
            if inv_range <= 0:
                return None, None, "Flat data: no contrast"

            # Use prominence instead of height. Height fails when baseline shifts, but prominence is robust.
            prominence = 0.03 * inv_range  # start at 3% of contrast
            # Minimum spacing between peaks (in points)
            min_distance_pts = max(1, len(inv) // (max(1, self.num_peaks) * 10))

            peak_idx, props = find_peaks(inv, prominence=prominence, distance=min_distance_pts)

            # If too strict, relax once
            if len(peak_idx) == 0:
                prominence = 0.015 * inv_range
                peak_idx, props = find_peaks(inv, prominence=prominence, distance=min_distance_pts)

            if len(peak_idx) == 0:
                return None, None, (
                    f"No peaks found. Try lowering prominence. inv_range={inv_range:.3g}, "
                    f"prominence={prominence:.3g}, min_distance_pts={min_distance_pts}"
                )

            # Sort by prominence and keep top N peaks
            prominences = props.get("prominences", np.ones_like(peak_idx, dtype=float))
            order = np.argsort(prominences)[::-1]
            peak_idx = peak_idx[order][: self.num_peaks]

            # --- Build initial guesses for fit ---
            p0 = []
            x_span = float(np.max(x) - np.min(x))
            gamma_guess = x_span / 80 if x_span > 0 else 1.0  # heuristic

            for idx in peak_idx:
                f0_guess = float(x[idx])
                # Dip amplitude guess (negative in y)
                A_guess = float(y_s[idx])  # y_s is baseline-corrected; dip is negative
                if A_guess > 0:
                    A_guess = -abs(A_guess)
                p0.extend([f0_guess, A_guess, gamma_guess])

            # Perform the fit
            popt, _ = curve_fit(multi_lorentzian, x, y0, p0=p0, maxfev=10000)

            # Generate high-resolution fit curve for plotting (re-add median)
            x_fit = np.linspace(np.min(x), np.max(x), 1000)
            y_fit = multi_lorentzian(x_fit, *popt) + np.median(y)

            # Build results text
            # Each peak -> a small block of 4 lines. We'll lay as many blocks side-by-side as will fit.
            blocks = []
            for i in range(self.num_peaks):
                f0 = popt[3 * i]
                A = popt[3 * i + 1]
                gamma = popt[3 * i + 2]
                blocks.append(
                    [
                        f"Peak {i+1}",
                        f"Centre: {(f0-NV_LO_freq)/1E6:.2f} MHz",
                        f"Contrast:  {(1-((np.max(y)+A)/np.max(y)))*100:.1f} %",
                        f"Width:  {gamma/1E6:.2f} MHz",
                    ]
                )

            # Column layout: choose how many columns based on an assumed character width.
            # This is GUI-independent (we don't have direct access to widget width here),
            # but monospace font in QM_GUI.py makes this approximation reasonable.
            col_w = 26  # chars per peak block column
            assumed_chars_per_line = 100
            cols = 8

            rows = []
            for start in range(0, len(blocks), cols):
                row_blocks = blocks[start : start + cols]
                max_h = max(len(b) for b in row_blocks)
                padded = [b + [""] * (max_h - len(b)) for b in row_blocks]
                for line_i in range(max_h):
                    rows.append("".join(padded[j][line_i].ljust(col_w) for j in range(len(padded))).rstrip())
                rows.append("")

            text = "ODMR Fit Results\n"
            text += f"Peaks fit: {self.num_peaks}    smoothing win: {win}    prominence: {prominence:.3g}\n\n"
            text += "\n".join(rows).rstrip() + "\n"

            return x_fit, y_fit, text

        except Exception as e:
            return None, None, f"Fit failed: {str(e)}"

    def restore_config(self):
        """Restore the original RF output gain from before compilation"""
        config["octaves"][octave]["RF_outputs"][1]["output_mode"] = 'triggered'
        if hasattr(self, 'original_rf_gain'):
            config["octaves"][octave]["RF_outputs"][1]["gain"] = self.original_rf_gain
            # Also restore on the actual Octave hardware.
            try:
                self.qm.octave.set_rf_output_gain("NV", self.original_rf_gain)
            except Exception as e:
                print(f"Warning: failed to restore Octave RF output gain for NV to {self.original_rf_gain} dB: {e}")

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
