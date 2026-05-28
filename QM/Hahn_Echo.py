"""
       HAHN ECHO MEASUREMENT (T2)
The program consists in playing two Hahn echo sequences successively (first ending with x90 and then with -x90)
and measure the photon counts received by the SPCM across varying idle times.

The data is then post-processed to determine the coherence time T2.

Prerequisites:
    - Ensure calibration of the different delays in the system (calibrate_delays).
    - Having updated the different delays in the configuration.
    - Having updated the NV frequency, labeled as "NV_IF_freq", in the configuration.
    - Having set the pi pulse amplitude and duration in the configuration

Next steps before going to the next node:
    -
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout
from qm import QuantumMachinesManager, SimulationConfig
from qm.qua import *
from qualang_tools.loops import from_array
from qualang_tools.results.data_handler import DataHandler
from scipy.optimize import curve_fit

from configuration import *  # noqa: F403
from experiment_base import ExperimentBase
from settings_dialog_base import SettingsDialogBase


class SettingsDialogHahnEcho(SettingsDialogBase):
    """Settings dialog persisted in QSettings."""

    SETTINGS_GROUP = "QM_HahnEcho"
    WINDOW_TITLE = "Hahn Echo Settings"

    SETTINGS_SCHEMA = {
        "time_max": {"label": "Time max (ns, for single τ):", "default": 100000, "type": int},
        "num_points": {"label": "Number of points:", "default": 30, "type": int},
        "num_averages": {"label": "Number of averages:", "default": 50_000_000, "type": int},
        "odmr_if_freq_mhz": {"label": "ODMR IF frequency (MHz):", "default": 23.0, "type": float},
        "rabi_freq_mhz": {"label": "Rabi frequency for π pulse (MHz):", "default": 7.65, "type": float},
        "gain": {"label": "Octave RF gain (dB):", "default": -5, "type": int},
    }


class HahnEcho(ExperimentBase):
    def __init__(self):
        self.qmm = None
        self.qm = None
        self.job = None

        self.is_running = False

        self.length_run = None
        self.num_points = None
        self.t_vec = None
        self.n_avg = None

        self.odmr_if_freq = None
        self.rabi_frequency_mhz = None
        self.gain = None

        self.hahn_echo = None

        self.original_rf_gain = None
        self.original_output_mode = None

        self.counts1 = None
        self.counts1_ref = None
        self.counts2 = None
        self.counts2_ref = None
        self.iteration = None

        self.save_data_dict = {"n_avg": None, "t_vec": None, "config": config}

    def restore_config(self):
        if self.original_output_mode is not None:
            config["octaves"][octave]["RF_outputs"][1]["output_mode"] = self.original_output_mode
        if self.original_rf_gain is not None:
            config["octaves"][octave]["RF_outputs"][1]["gain"] = self.original_rf_gain

        if self.original_rf_gain is not None and self.qm is not None:
            try:
                self.qm.octave.set_rf_output_gain("NV", self.original_rf_gain)
            except Exception as e:
                print(f"Warning: failed to restore Octave RF gain: {e}")

    def _update_pulse_lengths_from_rabi_freq(self):
        # Determine π and π/2 pulse lengths in ns, snapped to 4 ns clock.
        pi_pulse_len_ns = (1 / (2 * (self.rabi_frequency_mhz * u.MHz))) / 1e-9  # noqa: F405

        config["pulses"]["x180_pulse"]["length"] = pi_pulse_len_ns // 4 * 4
        config["pulses"]["x90_pulse"]["length"] = (pi_pulse_len_ns / 2) // 4 * 4
        config["pulses"]["-x90_pulse"]["length"] = (pi_pulse_len_ns / 2) // 4 * 4
        config["pulses"]["x270_pulse"]["length"] = (pi_pulse_len_ns * 1.5) // 4 * 4

    def compile_program(self):
        s = SettingsDialogHahnEcho.get_settings()
        self.length_run = int(s["time_max"])
        self.num_points = int(s["num_points"])
        self.n_avg = int(s["num_averages"])
        odmr_if_freq_mhz = float(s["odmr_if_freq_mhz"])
        rabi_freq_mhz = float(s["rabi_freq_mhz"])
        self.gain = int(s["gain"])

        self.odmr_if_freq = odmr_if_freq_mhz * u.MHz  # noqa: F405
        self.rabi_frequency_mhz = rabi_freq_mhz

        # Save original values to restore later so other experiments aren't affected.
        self.original_rf_gain = config["octaves"][octave]["RF_outputs"][1].get("gain")
        self.original_output_mode = config["octaves"][octave]["RF_outputs"][1].get("output_mode")

        # Apply requested gain for this experiment
        config["octaves"][octave]["RF_outputs"][1]["gain"] = self.gain

        self._update_pulse_lengths_from_rabi_freq()

        self.t_vec = np.arange(
            4, self.length_run // 4, max(1, self.length_run // (4 * self.num_points))
        )

        self.save_data_dict = {"n_avg": self.n_avg, "t_vec": self.t_vec, "config": config}

        self.qmm = QuantumMachinesManager(
            host=qop_ip, cluster_name=cluster_name, octave_calibration_db_path=calibration_db_dir
        )
        self.qm = self.qmm.open_qm(config, close_other_machines=True)

        # Apply gain on the Octave hardware as well (best-effort)
        try:
            self.qm.octave.set_rf_output_gain("NV", self.gain)
        except Exception as e:
            print(f"Warning: failed to set Octave RF gain for NV to {self.gain} dB: {e}")

        # Clear data arrays from previous runs
        self.counts1 = self.counts1_ref = self.counts2 = self.counts2_ref = self.iteration = None

        with program() as self.hahn_echo:
            counts = declare(int)
            times = declare(int, size=100)

            counts_1_st = declare_stream()
            counts_2_st = declare_stream()
            counts_1_ref_st = declare_stream()
            counts_2_ref_st = declare_stream()

            t = declare(int)
            n = declare(int)
            n_st = declare_stream()

            update_frequency("NV", self.odmr_if_freq)

            with for_(n, 0, n < self.n_avg, n + 1):
                with for_(*from_array(t, self.t_vec)):
                    # Sequence 1: x90 - τ - x180 - τ - x90
                    align()
                    play("x90" * amp(1), "NV")
                    wait(t, "NV")
                    play("x180" * amp(1), "NV")
                    wait(t, "NV")
                    play("x90" * amp(1), "NV")

                    align()
                    play("laser_ON", "AOM2")
                    measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
                    save(counts, counts_1_st)
                    measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
                    save(counts, counts_1_ref_st)
                    wait(wait_between_runs * u.ns)

                    # Sequence 2: x90 - τ - x180 - τ - -x90
                    align()
                    play("x90" * amp(1), "NV")
                    wait(t, "NV")
                    play("x180" * amp(1), "NV")
                    wait(t, "NV")
                    play("-x90" * amp(1), "NV")

                    align()
                    play("laser_ON", "AOM2")
                    measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
                    save(counts, counts_2_st)
                    measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
                    save(counts, counts_2_ref_st)
                    wait(wait_between_runs * u.ns)

                save(n, n_st)

            with stream_processing():
                counts_1_st.buffer(len(self.t_vec)).average().save("counts1")
                counts_1_ref_st.buffer(len(self.t_vec)).average().save("counts1_ref")
                counts_2_st.buffer(len(self.t_vec)).average().save("counts2")
                counts_2_ref_st.buffer(len(self.t_vec)).average().save("counts2_ref")
                n_st.save("iteration")

    def start_program(self):
        # Always recompile to apply any setting changes
        self.compile_program()
        try:
            simulate = False
            if simulate:
                simulation_config = SimulationConfig(duration=10_000)
                _job = self.qmm.simulate(config, self.hahn_echo, simulation_config)
                return

            self.is_running = True
            self.job = self.qm.execute(self.hahn_echo)
            results = fetching_tool(
                self.job,
                data_list=["counts1", "counts1_ref", "counts2", "counts2_ref", "iteration"],
                mode="live",
            )
            while results.is_processing() and self.is_running:
                self.counts1, self.counts1_ref, self.counts2, self.counts2_ref, self.iteration = (
                    results.fetch_all()
                )
                time.sleep(0.01)

            if self.counts1 is not None and self.counts1_ref is not None:
                self.save_data()
        except Exception as e:
            print(f"Error in HahnEcho.start_program: {e}")
            import traceback

            traceback.print_exc()
        finally:
            self.restore_config()

    def stop_program(self):
        self.is_running = False
        try:
            if self.job is not None:
                self.job.halt()
        except Exception as e:
            print(f"Error halting Hahn Echo job: {e}")
        finally:
            self.restore_config()

    def get_x(self) -> np.ndarray:
        if self.t_vec is None:
            return np.array([])
        return 8 * self.t_vec  # 2τ in ns (t is 4 ns units, used twice)

    def _safe_norm(self, a, b):
        if a is None or b is None:
            return None
        b_safe = np.where(b == 0, np.nan, b)
        return a / b_safe

    def get_y(self) -> np.ndarray:
        if self.t_vec is None:
            return np.array([])

        n1 = self._safe_norm(self.counts1, self.counts1_ref)
        n2 = self._safe_norm(self.counts2, self.counts2_ref)
        if n1 is None or n2 is None:
            return np.zeros(len(self.t_vec))

        diff = n1 - n2
        diff = np.nan_to_num(diff, nan=0.0, posinf=0.0, neginf=0.0)
        return diff

    def save_data(self):
        if self.t_vec is None:
            return

        script_name = Path(__file__).name
        data_handler = DataHandler(root_data_folder=save_dir)

        n1 = self._safe_norm(self.counts1, self.counts1_ref)
        n2 = self._safe_norm(self.counts2, self.counts2_ref)
        diff = None
        if n1 is not None and n2 is not None:
            diff = n1 - n2

        self.save_data_dict.update(
            {
                "counts1_data": self.counts1,
                "counts1_ref_data": self.counts1_ref,
                "normalized1_data": n1,
                "counts2_data": self.counts2,
                "counts2_ref_data": self.counts2_ref,
                "normalized2_data": n2,
                "diff_data": diff,
                "iteration": np.array([int(self.iteration)]) if self.iteration is not None else None,
            }
        )

        data_handler.additional_files = {script_name: script_name, **default_additional_files}
        data_handler.save_data(data=self.save_data_dict, name="hahn_echo")

    def get_plot_info(self):
        return {
            "x_text": "2τ",
            "x_units": "ns",
            "y_text": "Δ Normalised signal",
            "y_units": "arb. units",
        }

    @staticmethod
    def _t2_decay(t, A, T2, C):
        """Single exponential decay used for Hahn Echo T2 fit.

        Model: A * exp(-(t/T2)) + C

        Notes:
            - t and T2 are in the same units (we fit in ns)
            - T2 is clipped to stay positive for numerical stability
        """
        t = np.asarray(t)
        T2 = np.clip(T2, 1e-12, np.inf)
        return A * np.exp(-(t / T2)) + C

    def _get_norm_traces(self):
        """Return (x, norm1, norm2, diff) or (None, None, None, None) if unavailable."""
        x = self.get_x()
        if x.size == 0:
            return None, None, None, None

        n1 = self._safe_norm(self.counts1, self.counts1_ref)
        n2 = self._safe_norm(self.counts2, self.counts2_ref)
        if n1 is None or n2 is None:
            return None, None, None, None

        # Ensure numpy arrays
        n1 = np.asarray(n1)
        n2 = np.asarray(n2)
        diff = np.nan_to_num(n1 - n2, nan=0.0, posinf=0.0, neginf=0.0)
        return np.asarray(x), np.nan_to_num(n1, nan=0.0, posinf=0.0, neginf=0.0), np.nan_to_num(
            n2, nan=0.0, posinf=0.0, neginf=0.0
        ), diff

    def fit(self):
        """Fit the difference trace to extract T2.

        Returns:
            (x_fit, y_fit, text)
        """
        x, norm1, norm2, diff = self._get_norm_traces()
        if x is None or diff is None:
            return np.array([]), np.array([]), "No data to fit"

        x_arr = np.asarray(x, dtype=float)
        y_arr = np.asarray(diff, dtype=float)

        # Basic sanity checks
        if x_arr.size < 5:
            return np.array([]), np.array([]), "Not enough points to fit"

        # Remove any non-finite points
        mask = np.isfinite(x_arr) & np.isfinite(y_arr)
        x_arr = x_arr[mask]
        y_arr = y_arr[mask]
        if x_arr.size < 5:
            return np.array([]), np.array([]), "Not enough finite points to fit"

        # Bounds: enforce T2 >= 0
        bounds = ([-np.inf, 0.0, -np.inf], [np.inf, np.inf, np.inf])

        try:
            # Baseline guess: median of last ~20% of points (or at least 5 points)
            tail_n = max(5, int(0.2 * x_arr.size))
            C0 = float(np.median(y_arr[-tail_n:]))

            # Amplitude guess: early-time deviation from baseline
            A0 = float(y_arr[0] - C0)
            if np.isclose(A0, 0.0):
                A0 = float(0.5 * (np.max(y_arr) - np.min(y_arr)))
                if float(np.median(y_arr[:tail_n])) < C0:
                    A0 = -abs(A0)
                else:
                    A0 = abs(A0)

            # T2 guess: a fraction of the x-span
            x_span = float(np.max(x_arr) - np.min(x_arr))
            T20 = max(1.0, 0.3 * x_span)

            popt, pcov = curve_fit(
                self._t2_decay,
                x_arr,
                y_arr,
                p0=(A0, T20, C0),
                bounds=bounds,
                maxfev=50000,
            )
            A_fit, T2_fit, C_fit = popt
            perr = np.sqrt(np.diag(pcov)) if pcov is not None else np.array([np.nan, np.nan, np.nan])
            T2_err = float(perr[1]) if perr.size >= 2 else float("nan")

            x_fit = np.linspace(float(np.min(x_arr)), float(np.max(x_arr)), 500)
            y_fit = self._t2_decay(x_fit, *popt)

            # Display in µs (x is ns)
            text = f"T2 = {T2_fit / 1000:.0f} ± {T2_err / 1000:.0f} µs"
            return x_fit, y_fit, text
        except Exception as e:
            return np.array([]), np.array([]), f"Fit failed: {e}"
