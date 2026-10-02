"""
       XY8 MEASUREMENT (tau sweep)
The program consists in playing two XY8-N sequences successively (first ending with x90 and then with -x90)
and measure the photon counts received by the SPCM across varying idle times between pi-pulses.
The values `tau_vec` are the times between pi-pulse centers. From this the pulse spacings are calculated by
subtracting the duration of the pi-pulse. The same is done for the half-spacing before/after the pi/2-pulses,
assuming the pi/2-pulse has half the length of the pi-pulse.

The data is then post-processed to determine the coherence time T2 associated with the XY8-N tau sweep.

The sequence is defined in the following way:
x90 - [t - x180 - 2t - y180 - 2t - x180 - 2t - y180 - 2t - y180 - 2t - x180 - 2t - y180 - 2t - x180 - t] ^ xy8_order - x90

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
from qm import QuantumMachinesManager, SimulationConfig
from qm.qua import *
from qualang_tools.results.data_handler import DataHandler
from scipy.optimize import curve_fit

from experiment_base import *
from settings_dialog_base import SettingsDialogBase
from PyQt6.QtWidgets import QPushButton


class SettingsDialogXY8(SettingsDialogBase):
    """Settings dialog persisted in QSettings."""
    def __init__(self, parent=None):
        super().__init__(parent)
        import_button = QPushButton("Import Values from Hahn Echo")
        import_button.clicked.connect(self.import_values)
        self.layout().addWidget(import_button)

    def import_values(self):
        from Hahn_Echo import SettingsDialogHahnEcho
        echo_settings = SettingsDialogHahnEcho.get_settings()
        self.settable_values["odmr_if_freq_mhz"].setText(str(echo_settings["odmr_if_freq_mhz"]))
        self.settable_values["gain"].setText(str(echo_settings["gain"]))
        try:
            self.settable_values["rabi_freq_mhz"].setText(str(echo_settings["rabi_freq_mhz"]))
        except KeyError:
            print("Rabi frequency not found in Hahn Echo settings. Please run a Hahn Echo on the current session or enter manually.")

    SETTINGS_GROUP = "QM_XY8"
    WINDOW_TITLE = "XY8 Settings"

    SETTINGS_SCHEMA = {
        "time_max": {"label": "Tau max (ns, pulse-center spacing):", "default": 4000, "type": int},
        "num_points": {"label": "Number of points:", "default": 24, "type": int},
        "xy8_order": {"label": "XY8 order n:", "default": 4, "type": int},
        "num_averages": {"label": "Number of averages:", "default": 1_000_000, "type": int},
        "odmr_if_freq_mhz": {"label": "ODMR IF frequency (MHz):", "default": 23.0, "type": float},
        "rabi_freq_mhz": {"label": "Rabi frequency for π pulse (MHz):", "default": 7.65, "type": float},
        "gain": {"label": "Octave RF gain (dB):", "default": -5, "type": int},
    }


class XY8(ExperimentBase):
    def __init__(self):
        super().__init__()
        self.qmm = None
        self.qm = None
        self.job = None

        self.is_running = False

        self.time_max = None
        self.num_points = None
        self.xy8_order = None
        self.n_avg = None

        self.tau_vec = None
        self.tau_vec_spacing = None
        self.tau_half_vec_spacing = None
        self.reference_wait = None
        self.reference_readout = None

        self.odmr_if_freq = None
        self.rabi_frequency_mhz = None
        self.gain = None

        self.xy8_prog = None

        self.original_rf_gain = None
        self.original_output_mode = None

        self.counts1 = None
        self.counts1_ref = None
        self.counts2 = None
        self.counts2_ref = None
        self.iteration = None

        self.save_data_dict = {"n_avg": None, "t_vec": None, "xy8_order": None, "config": config}

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

    @staticmethod
    def _xy8_block(tau):
        """A single XY8 block: X - Y - X - Y - Y - X - Y - X, interspersed with waits of `tau`."""
        play("x180", "NV")  # 1 X
        wait(tau, "NV")

        play("y180", "NV")  # 2 Y
        wait(tau, "NV")

        play("x180", "NV")  # 3 X
        wait(tau, "NV")

        play("y180", "NV")  # 4 Y
        wait(tau, "NV")

        play("y180", "NV")  # 5 Y
        wait(tau, "NV")

        play("x180", "NV")  # 6 X
        wait(tau, "NV")

        play("y180", "NV")  # 7 Y
        wait(tau, "NV")

        play("x180", "NV")  # 8 X

    def _xy8_n(self, tau, order, i):
        """Full XY8-N sequence. The first block is outside the loop to avoid the extra
        delay caused by two consecutive wait commands."""
        self._xy8_block(tau)
        with for_(i, 1, i <= order - 1, i + 1):
            wait(tau, "NV")
            self._xy8_block(tau)

    def compile_program(self):
        s = SettingsDialogXY8.get_settings()
        self.time_max = int(s["time_max"])
        self.num_points = max(1, int(s["num_points"]))
        self.xy8_order = int(s["xy8_order"])
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

        self._update_pulse_lengths_from_rabi_freq(self.rabi_frequency_mhz)
        # y180 is a separate pulse entry in the config; keep it in sync with x180 since XY8 uses both.
        config["pulses"]["y180_pulse"]["length"] = config["pulses"]["x180_pulse"]["length"]

        # Cast to int: _update_pulse_lengths_from_rabi_freq computes these with plain float
        # arithmetic, so the config values can come back as floats (e.g. 64.0). Subtracting a
        # float from the int tau_vec array would silently upcast it to float64, which then makes
        # for_each_ declare a QUA `fixed` array instead of `int` -- and fixed numbers are only
        # representable in [-8, 8), so any real spacing value overflows it at compile time.
        x180_len = int(config["pulses"]["x180_pulse"]["length"])
        x90_len = int(config["pulses"]["x90_pulse"]["length"])

        # tau_vec: times between pi-pulse centers, in clock cycles (4 ns). Each value must be a
        # multiple of 2 clock cycles to ensure that the half-spacing is a multiple of a clock cycle.
        tau_min_cc = 12
        tau_max_cc = max(tau_min_cc + 2, self.time_max // 8)
        step_cc = max(1, (tau_max_cc - tau_min_cc) // self.num_points)
        self.tau_vec = 2 * np.arange(tau_min_cc, tau_max_cc, step_cc)

        tau_vec_spacing = self.tau_vec - x180_len // 4  # interpulse spacing: end of pulse to start of next
        tau_half_vec_spacing = self.tau_vec // 2 - x90_len // 4  # spacing around the pi/2 pulses

        # Remove any tau values whose interpulse spacing would be too short to play.
        for ii in reversed(range(len(self.tau_vec))):
            if tau_half_vec_spacing[ii] < 4:
                tau_half_vec_spacing = np.delete(tau_half_vec_spacing, ii)
                tau_vec_spacing = np.delete(tau_vec_spacing, ii)
                self.tau_vec = np.delete(self.tau_vec, ii)

        self.tau_vec_spacing = tau_vec_spacing
        self.tau_half_vec_spacing = tau_half_vec_spacing

        # Determine whether there's room for a second (reference) readout within the same laser pulse.
        self.reference_wait = initialization_len_1 // 4 - 2 * meas_len_1 // 4 - 25  # in clock cycles
        self.reference_readout = self.reference_wait >= 4

        self.save_data_dict = {
            "n_avg": self.n_avg,
            "t_vec": self.tau_vec,
            "xy8_order": self.xy8_order,
            "config": config,
        }

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

        with program() as self.xy8_prog:
            tau_spacing = declare(int)
            tau_half_spacing = declare(int)
            n = declare(int)
            i = declare(int)

            counts = declare(int)
            times = declare(int, size=100)
            counts_1_st = declare_stream()
            counts_2_st = declare_stream()
            counts_1_ref_st = declare_stream()
            counts_2_ref_st = declare_stream()
            n_st = declare_stream()

            update_frequency("NV", self.odmr_if_freq)

            with for_(n, 0, n < self.n_avg, n + 1):
                with for_each_((tau_spacing, tau_half_spacing), (self.tau_vec_spacing, self.tau_half_vec_spacing)):
                    wait(4)  # short wait to assign the variables of the zipped loop
                    # First XY8 sequence: x90 - XY8-order block - x90
                    play("x90", "NV")
                    wait(tau_half_spacing, "NV")
                    self._xy8_n(tau_spacing, self.xy8_order, i)
                    wait(tau_half_spacing, "NV")
                    play("x90", "NV")
                    align()  # Play the laser pulse after the XY8 sequence
                    play("laser_ON", "AOM2")
                    measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
                    save(counts, counts_1_st)
                    measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
                    save(counts, counts_1_ref_st)
                    wait(wait_between_runs * u.ns, "AOM2")

                    align()
                    # Second XY8 sequence: x90 - XY8-order block - -x90
                    play("x90", "NV")
                    wait(tau_half_spacing, "NV")
                    self._xy8_n(tau_spacing, self.xy8_order, i)
                    wait(tau_half_spacing, "NV")
                    play("-x90", "NV")
                    align()  # Play the laser pulse after the XY8 sequence
                    play("laser_ON", "AOM2")
                    measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
                    save(counts, counts_2_st)
                    measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
                    save(counts, counts_2_ref_st)
                    wait(wait_between_runs * u.ns, "AOM2")

                self.refocus_loop()

                save(n, n_st)

            with stream_processing():
                counts_1_st.buffer(len(self.tau_vec)).average().save("counts1")
                counts_1_ref_st.buffer(len(self.tau_vec)).average().save("counts1_ref")
                counts_2_st.buffer(len(self.tau_vec)).average().save("counts2")
                counts_2_ref_st.buffer(len(self.tau_vec)).average().save("counts2_ref")
                n_st.save("iteration")

    def start_program(self):
        # Always recompile to apply any setting changes
        self.compile_program()
        try:
            simulate = False
            if simulate:
                simulation_config = SimulationConfig(duration=10_000)
                _job = self.qmm.simulate(config, self.xy8_prog, simulation_config)
                return

            self.is_running = True
            self.job = self.qm.execute(self.xy8_prog)
            results = fetching_tool(
                self.job,
                data_list=["counts1", "counts1_ref", "counts2", "counts2_ref", "iteration"],
                mode="live",
            )
            self.start_signal_listener()
            while results.is_processing() and self.is_running:
                self.counts1, self.counts1_ref, self.counts2, self.counts2_ref, self.iteration = (
                    results.fetch_all()
                )
                time.sleep(0.01)

            if self.counts1 is not None and self.counts1_ref is not None:
                self.save_data()
        except Exception as e:
            print(f"Error in XY8.start_program: {e}")
            import traceback

            traceback.print_exc()
        finally:
            self.restore_config()
            self.close_signal_listener()

    def stop_program(self):
        self.is_running = False
        try:
            if self.job is not None:
                self.job.halt()
        except Exception as e:
            print(f"Error halting XY8 job: {e}")
        finally:
            self.restore_config()
            self.close_signal_listener()

    def get_x(self) -> np.ndarray:
        if self.tau_vec is None:
            return np.array([])
        return 4 * self.tau_vec  # tau (pulse-center spacing) in ns

    def _safe_norm(self, a, b):
        if a is None or b is None:
            return None
        b_safe = np.where(b == 0, np.nan, b)
        return a / b_safe

    def get_y(self) -> np.ndarray:
        if self.tau_vec is None:
            return np.array([])

        n1 = self._safe_norm(self.counts1, self.counts1_ref)
        n2 = self._safe_norm(self.counts2, self.counts2_ref)
        if n1 is None or n2 is None:
            return np.zeros(len(self.tau_vec))

        diff = n1 - n2
        diff = np.nan_to_num(diff, nan=0.0, posinf=0.0, neginf=0.0)
        return diff

    def save_data(self):
        if self.tau_vec is None:
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
        data_handler.save_data(data=self.save_data_dict, name="xy8")

    def get_plot_info(self):
        return {
            "x_text": "τ (pulse spacing)",
            "x_units": "ns",
            "y_text": "Δ Normalised signal",
            "y_units": "arb. units",
        }

    @staticmethod
    def _t2_decay(t, A, T2, C, p):
        """Stretched exponential decay used for the XY8 T2 fit.

        Model: A * exp(-(t/T2)^p) + C

        Notes:
            - t and T2 are in the same units (we fit in ns)
            - T2 is clipped to stay positive and p is clipped to a sane range for numerical stability
        """
        t = np.asarray(t)
        T2 = np.clip(T2, 1e-12, np.inf)
        p = np.clip(p, 0.3, 8.0)
        return A * np.exp(-np.power(t / T2, p)) + C

    def _get_norm_traces(self):
        """Return (x, norm1, norm2, diff) or (None, None, None, None) if unavailable."""
        x = self.get_x()
        if x.size == 0:
            return None, None, None, None

        n1 = self._safe_norm(self.counts1, self.counts1_ref)
        n2 = self._safe_norm(self.counts2, self.counts2_ref)
        if n1 is None or n2 is None:
            return None, None, None, None

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

        if x_arr.size < 5:
            return np.array([]), np.array([]), "Not enough points to fit"

        mask = np.isfinite(x_arr) & np.isfinite(y_arr)
        x_arr = x_arr[mask]
        y_arr = y_arr[mask]
        if x_arr.size < 5:
            return np.array([]), np.array([]), "Not enough finite points to fit"

        # Bounds: enforce T2 >= 0 and a physically sane stretching exponent p
        bounds = ([-np.inf, 0.0, -np.inf, 0.3], [np.inf, np.inf, np.inf, 8.0])

        try:
            tail_n = max(5, int(0.2 * x_arr.size))
            C0 = float(np.median(y_arr[-tail_n:]))

            A0 = float(y_arr[0] - C0)
            if np.isclose(A0, 0.0):
                A0 = float(0.5 * (np.max(y_arr) - np.min(y_arr)))
                if float(np.median(y_arr[:tail_n])) < C0:
                    A0 = -abs(A0)
                else:
                    A0 = abs(A0)

            x_span = float(np.max(x_arr) - np.min(x_arr))
            T20 = max(1.0, 0.3 * x_span)

            popt, pcov = curve_fit(
                self._t2_decay,
                x_arr,
                y_arr,
                p0=(A0, T20, C0, 1.5),
                bounds=bounds,
                maxfev=50000,
            )
            A_fit, T2_fit, C_fit, p_fit = popt
            perr = np.sqrt(np.diag(pcov)) if pcov is not None else np.array([np.nan] * 4)
            T2_err = float(perr[1]) if perr.size >= 2 else float("nan")

            x_fit = np.linspace(float(np.min(x_arr)), float(np.max(x_arr)), 500)
            y_fit = self._t2_decay(x_fit, *popt)

            text = f"T2 = {T2_fit / 1000:.1f} ± {T2_err / 1000:.1f} µs, p = {p_fit:.2f}"
            return x_fit, y_fit, text
        except Exception as e:
            return np.array([]), np.array([]), f"Fit failed: {e}"
