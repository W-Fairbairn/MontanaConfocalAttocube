"""
       XY8 MEASUREMENT (tau sweep)
The program consists in playing two XY8-N sequences successively (first ending with x90 and then with -x90)
and measure the photon counts received by the SPCM across varying idle times between pi-pulses.
The swept setting is the total evolution time of the sequence, T = 8 * xy8_order * tau, which is divided
by 8 * xy8_order to get `tau_vec`, the times between pi-pulse centers. From this the pulse spacings are
calculated by subtracting the duration of the pi-pulse. The same is done for the half-spacing before/after
the pi/2-pulses, assuming the pi/2-pulse has half the length of the pi-pulse. Points where this would make
the gap shorter than the minimum pulse duration (16 ns) are dropped.

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

import numpy as np
from qm import QuantumMachinesManager, SimulationConfig
from qm.qua import *
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
        "time_max": {"label": "Total evolution time max (ns):", "default": 1_000_000, "type": int},
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
        play("gap", "NV", duration=tau)

        play("y180", "NV")  # 2 Y
        play("gap", "NV", duration=tau)

        play("x180", "NV")  # 3 X
        play("gap", "NV", duration=tau)

        play("y180", "NV")  # 4 Y
        play("gap", "NV", duration=tau)

        play("y180", "NV")  # 5 Y
        play("gap", "NV", duration=tau)

        play("x180", "NV")  # 6 X
        play("gap", "NV", duration=tau)

        play("y180", "NV")  # 7 Y
        play("gap", "NV", duration=tau)

        play("x180", "NV")  # 8 X

    def _xy8_n(self, tau, order, rep_counter):
        self._xy8_block(tau)
        if order == 1:
            return
        if order >= 3:
            with for_(rep_counter, 0, rep_counter < order - 2, rep_counter + 1):
                play("gap", "NV", duration=tau)
                self._xy8_block(tau)
        play("gap", "NV", duration=tau)
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
        x180_len = int(config["pulses"]["x180_pulse"]["length"])
        x90_len = int(config["pulses"]["x90_pulse"]["length"])

        # tau_vec: times between pi-pulse centers, in clock cycles (4 ns). Each value must be a
        # multiple of 2 clock cycles to ensure that the half-spacing is a multiple of a clock cycle.
        # `self.time_max` is the total evolution time (ns) of the full XY8-N sequence:
        # T = 8 * xy8_order * tau, so it's divided across the 8*xy8_order inter-pulse
        # intervals to get the max tau to sweep.
        n_tau_intervals = 8 * self.xy8_order
        tau_min_cc = 12
        tau_max_cc = max(tau_min_cc + 2, self.time_max // (2 * 4 * n_tau_intervals))
        step_cc = max(1, (tau_max_cc - tau_min_cc) // self.num_points)
        self.tau_vec = 2 * np.arange(tau_min_cc, tau_max_cc, step_cc)

        tau_vec_spacing = self.tau_vec - x180_len // 4  # interpulse spacing: end of pulse to start of next
        tau_half_vec_spacing = self.tau_vec // 2 - x90_len // 4  # spacing around the pi/2 pulses

        # Remove any tau values whose interpulse spacing (full or half) would be shorter than
        # the minimum pulse/wait duration of 4 clock cycles (16 ns). Small total evolution
        # times divided across many XY8 intervals can otherwise push tau below this limit.
        min_gap_cc = 4
        for ii in reversed(range(len(self.tau_vec))):
            if tau_half_vec_spacing[ii] < min_gap_cc or tau_vec_spacing[ii] < min_gap_cc:
                tau_half_vec_spacing = np.delete(tau_half_vec_spacing, ii)
                tau_vec_spacing = np.delete(tau_vec_spacing, ii)
                self.tau_vec = np.delete(self.tau_vec, ii)

        self.tau_vec_spacing = tau_vec_spacing
        self.tau_half_vec_spacing = tau_half_vec_spacing

        # Determine whether there's room for a second (reference) readout within the same laser pulse.
        self.reference_wait = initialization_len_1 // 4 - 2 * meas_len_1 // 4 - 25  # in clock cycles
        self.reference_readout = self.reference_wait >= 4

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
            rep_counter = declare(int)

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
                    # Not wrapped in strict_timing_(): it cannot coexist with the
                    # real-time for_ loop inside _xy8_n (hard CompilationException).
                    # Exactness is instead established empirically -- see _xy8_n.
                    align()
                    play("x90", "NV")
                    play("gap", "NV", duration=tau_half_spacing)
                    self._xy8_n(tau_spacing, self.xy8_order, rep_counter)
                    play("gap", "NV", duration=tau_half_spacing)
                    play("x90", "NV")
                    align()  # Play the laser pulse after the XY8 sequence
                    play("laser_ON", "AOM2")
                    measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
                    save(counts, counts_1_st)
                    measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
                    save(counts, counts_1_ref_st)
                    wait(wait_between_runs * u.ns)

                    align()
                    # Second XY8 sequence: x90 - XY8-order block - -x90
                    play("x90", "NV")
                    play("gap", "NV", duration=tau_half_spacing)
                    self._xy8_n(tau_spacing, self.xy8_order, rep_counter)
                    play("gap", "NV", duration=tau_half_spacing)
                    play("-x90", "NV")
                    align()  # Play the laser pulse after the XY8 sequence
                    play("laser_ON", "AOM2")
                    measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
                    save(counts, counts_2_st)
                    measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
                    save(counts, counts_2_ref_st)
                    wait(wait_between_runs * u.ns)

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
                # Simulates the QUA program for the specified duration
                simulation_config = SimulationConfig(duration=10_000)  # In clock cycles = 4ns
                # Simulate blocks python until the simulation is done
                job = self.qmm.simulate(config, self.xy8_prog, simulation_config)
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
        # Total free evolution time (ns): T = 8 * xy8_order * tau
        return 8 * self.xy8_order * (4 * self.tau_vec)

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

    def get_save_name(self):
        return "xy8"

    def get_save_data(self):
        if self.tau_vec is None:
            return {}

        n1 = self._safe_norm(self.counts1, self.counts1_ref)
        n2 = self._safe_norm(self.counts2, self.counts2_ref)
        diff = (n1 - n2) if (n1 is not None and n2 is not None) else None

        return {
            "n_avg": self.n_avg,
            "t_vec": self.tau_vec,
            "xy8_order": self.xy8_order,
            "counts1_data": self.counts1,
            "counts1_ref_data": self.counts1_ref,
            "normalized1_data": n1,
            "counts2_data": self.counts2,
            "counts2_ref_data": self.counts2_ref,
            "normalized2_data": n2,
            "diff_data": diff,
            "iteration": np.array([int(self.iteration)]) if self.iteration is not None else None,
        }

    def get_plot_info(self):
        return {
            "x_text": "Total free evolution time",
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
