"""
       HBT Measurement (g2 photon correlation)

Two independent SPCMs (elements "photon_in_read" / "photon_in_read_2"), each
looking at one output of a 50/50 beamsplitter in the confocal collection path,
are time-tagged continuously while the excitation laser is left on. Within
every acquisition window the arrival times on channel 1 are cross-correlated
against the arrival times on channel 2, and the resulting delay histogram is
accumulated and normalized to give the second-order correlation function
g2(tau). A true single photon emitter shows g2(0) < 0.5.
"""

from qm.qua import *
from qm import SimulationConfig

from configuration import *
from qualang_tools.results.data_handler import DataHandler
import numpy as np
from pathlib import Path
import time
from scipy.optimize import curve_fit
from PyQt6.QtCore import QSettings

from experiment_base import ExperimentBase
from settings_dialog_base import SettingsDialogBase

settings = QSettings("Diamond", "QM_HBT")

# max number of photon detections expected within a single acquisition window
# on either channel. should be big enough so time tages dont get missed
TIME_TAG_BUFFER_SIZE = 200


class SettingsDialogHBT(SettingsDialogBase):
    SETTINGS_GROUP = "QM_HBT"
    WINDOW_TITLE = "HBT Settings"

    SETTINGS_SCHEMA = {
        "tau_max": {
            "label": "Correlation range +/- (ns):",
            "default": 200,
            "type": int,
        },
        "bin_width": {
            "label": "Correlation bin width (ns):",
            "default": 4,
            "type": int,
        },
        "num_windows": {
            "label": "Number of acquisition windows:",
            "default": 10_000_000,
            "type": int,
        },
    }


class HBT(ExperimentBase):
    def __init__(self):

        self.qmm = get_qmm()  # shared QuantumMachinesManager - see configuration.py
        self.qm = self.qmm.open_qm(config, close_other_machines=True)

        ##################
        #   Parameters   #
        ##################
        self.window_len = long_meas_len_1  # acquisition window per shot, in ns
        self.shots_per_batch = 2000  # shots between refocus checks
        self.tau_max, self.bin_width, self.num_windows = None, None, None
        self.bin_edges, self.bin_centers = None, None
        self.is_running = False
        self.HBT_prog = None
        self.job = None

        # Running accumulators for the g2 histogram
        self.coincidence_hist = None
        self.total_counts_1 = 0
        self.total_counts_2 = 0
        self.total_windows = 0

        # Data to save
        self.save_data_dict = {"config": config}

    def compile_program(self):
        s = SettingsDialogHBT.get_settings()
        self.tau_max = int(s["tau_max"])
        self.bin_width = max(1, int(s["bin_width"]))
        self.num_windows = int(s["num_windows"])

        self.bin_edges = np.arange(
            -self.tau_max, self.tau_max + self.bin_width, self.bin_width
        )
        self.bin_centers = (self.bin_edges[:-1] + self.bin_edges[1:]) / 2
        self.coincidence_hist = np.zeros(len(self.bin_centers), dtype=np.int64)
        self.total_counts_1 = 0
        self.total_counts_2 = 0
        self.total_windows = 0

        n_bins = len(self.bin_centers)

        with program() as self.HBT_prog:
            times1 = declare(int, size=TIME_TAG_BUFFER_SIZE)
            times2 = declare(int, size=TIME_TAG_BUFFER_SIZE)
            counts1 = declare(int)
            counts2 = declare(int)
            n = declare(int)  # shot index within a refocus batch
            i = declare(int)  # correlation loop var, channel 1 tag index
            j = declare(int)  # correlation loop var, channel 2 tag index
            k = declare(int)  # loop var for flushing the histogram array
            dt = declare(int)
            bin_idx = declare(int)

            # Persistent accumulators: computed on-chip and never reset mid-run,
            # so only a small periodic snapshot needs to be streamed to the host
            # instead of every individual raw photon time tag (which overwhelms
            # the result-streaming connection at realistic count rates).
            hist = declare(int, size=n_bins)
            total1 = declare(int)
            total2 = declare(int)
            total_shots = declare(int)

            n_st = declare_stream()
            hist_st = declare_stream()
            total1_st = declare_stream()
            total2_st = declare_stream()
            total_shots_st = declare_stream()

            with infinite_loop_():
                with for_(n, 0, n < self.shots_per_batch, n + 1):
                    align()
                    # Retrigger the AOM gate every window so the laser stays
                    # continuously on (CW-like excitation) across the run.
                    play("gate_on_long", "aom_gate")
                    measure(
                        "long_readout",
                        "photon_in_read",
                        time_tagging.analog(times1, self.window_len, counts1),
                    )
                    measure(
                        "long_readout",
                        "photon_in_read_2",
                        time_tagging.analog(times2, self.window_len, counts2),
                    )

                    # Cross-correlate this window's tags on-chip and fold
                    # straight into the running histogram - tags are only ever
                    # compared within the same window, never across windows.
                    with for_(i, 0, i < counts1, i + 1):
                        with for_(j, 0, j < counts2, j + 1):
                            assign(dt, times2[j] - times1[i])
                            with if_((dt >= -self.tau_max) & (dt < self.tau_max)):
                                assign(
                                    bin_idx,
                                    Cast.to_int((dt + self.tau_max) / self.bin_width),
                                )
                                with if_(bin_idx >= n_bins):
                                    assign(bin_idx, n_bins - 1)
                                assign(hist[bin_idx], hist[bin_idx] + 1)

                    assign(total1, total1 + counts1)
                    assign(total2, total2 + counts2)
                    assign(total_shots, total_shots + 1)

                save(n, n_st)  # save number of shots completed in this batch
                # Flush a full snapshot of the accumulators once per batch -
                # a few hundred values every shots_per_batch shots, instead of
                # every raw tag every shot.
                with for_(k, 0, k < n_bins, k + 1):
                    save(hist[k], hist_st)
                save(total1, total1_st)
                save(total2, total2_st)
                save(total_shots, total_shots_st)

                with while_(IO1):  # refocusing loop
                    play("gate_on_long", "aom_gate")
                    wait(wait_for_initialization * u.ns, "aom_gate")
                    align()

            with stream_processing():
                n_st.save("iteration")
                hist_st.buffer(n_bins).save_all("histogram")
                total1_st.save_all("total1")
                total2_st.save_all("total2")
                total_shots_st.save_all("total_shots")

    def get_x(self):
        return self.bin_centers

    def _normalized_g2(self):
        if (
            self.total_windows == 0
            or self.total_counts_1 == 0
            or self.total_counts_2 == 0
        ):
            return np.zeros(len(self.bin_centers))
        total_time_ns = self.total_windows * self.window_len
        expected_uncorrelated = (
            self.total_counts_1 * self.total_counts_2 * self.bin_width / total_time_ns
        )
        if expected_uncorrelated <= 0:
            return np.zeros(len(self.bin_centers))
        return self.coincidence_hist / expected_uncorrelated

    def get_y(self):
        if self.bin_centers is None:
            return None
        return self._normalized_g2()

    def get_err(self):
        if self.coincidence_hist is None or self.total_windows == 0:
            return None
        total_time_ns = self.total_windows * self.window_len
        expected_uncorrelated = (
            self.total_counts_1 * self.total_counts_2 * self.bin_width / total_time_ns
        )
        if expected_uncorrelated <= 0:
            return None
        # Poissonian shot noise on the raw coincidence counts in each bin
        raw_err = np.sqrt(np.maximum(self.coincidence_hist, 1))
        return raw_err / expected_uncorrelated

    def stop_program(self):
        self.is_running = False
        try:
            self.job.halt()
        except Exception as e:
            print(f"Error halting the job: {e}")
        finally:
            self.stop_refocus_listener()

    def save_data(self):
        script_name = Path(__file__).name
        data_handler = DataHandler(root_data_folder=save_dir)
        self.save_data_dict.update(
            {
                "tau_ns": self.bin_centers,
                "g2": self.get_y(),
                "coincidence_counts": self.coincidence_hist,
                "total_counts_1": self.total_counts_1,
                "total_counts_2": self.total_counts_2,
                "total_windows": self.total_windows,
            }
        )
        data_folder = data_handler.save_data(
            data=self.save_data_dict, name=script_name.split(".")[0]
        )
        csv_path = Path(data_folder) / f"{script_name.split('.')[0]}_data.csv"
        np.savetxt(
            csv_path,
            np.column_stack((self.bin_centers, self.get_y(), self.coincidence_hist)),
            delimiter=",",
            header="tau (ns), g2, raw coincidences",
            comments="",
        )
        self.save_plot_png(Path(data_folder) / f"{script_name.split('.')[0]}_plot.png")

    def get_plot_info(self):
        return {
            "x_text": "Delay time",
            "x_units": "ns",
            "y_text": "g2(tau)",
            "y_units": "normalized coincidences",
        }

    def fit(self):
        x, y, err = self.get_x(), self.get_y(), self.get_err()
        if x is None or y is None or not np.any(y):
            return [np.array([]), np.array([]), "No data to fit"]

        def g2_model(tau, a, tau1, tau2):
            # Standard 3-level model: antibunching dip (tau1) plus a possible
            # bunching shoulder from shelving in the metastable state (tau2).
            return 1 - (1 + a) * np.exp(-np.abs(tau) / tau1) + a * np.exp(
                -np.abs(tau) / tau2
            )

        popt, pcov = curve_fit(
            g2_model,
            x,
            y,
            p0=(0.5, 20, 200),
            sigma=err,
            absolute_sigma=err is not None,
            maxfev=10000,
        )
        a_fit, tau1_fit, tau2_fit = popt
        perr = np.sqrt(np.diag(pcov))
        interp_x = np.linspace(min(x), max(x), 500)
        fit_y = g2_model(interp_x, *popt)
        g2_zero = g2_model(0, *popt)
        text = (
            f"g2(0) = {g2_zero:.3f}\n"
            f"tau1 = {tau1_fit:.1f} +/- {perr[1]:.1f} ns\n"
            f"tau2 = {tau2_fit:.1f} +/- {perr[2]:.1f} ns"
        )
        return [interp_x, fit_y, text]

    def start_program(self):
        try:
            # Always recompile to apply any setting changes. Inside the try
            # (not before it) so a failure here - e.g. the OPX connection
            # (QuantumMachinesManager/open_qm(), real network I/O to
            # qop_ip) hanging or erroring - is caught and logged instead of
            # silently killing this background thread while the GUI keeps
            # thinking a measurement is running.
            self.compile_program()
            simulate = False
            if simulate:
                # For debugging the waveform, it's often convenient to simulate a single iteration:
                simulation_config = SimulationConfig(
                    duration=30_000
                )  # In clock cycles = 4ns
                # Simulate blocks python until the simulation is done
                job = self.qmm.simulate(config, self.HBT_prog, simulation_config)
                # Get the simulated samples
                samples = job.get_simulated_samples()
                # Plot the simulated samples (this will show all pulses/traces produced by the program)
                samples.con1.plot()
                # Get the waveform report object
                waveform_report = job.get_simulated_waveform_report()
                # Cast the waveform report to a python dictionary
                waveform_dict = waveform_report.to_dict()
                # Visualize and save the waveform report
                waveform_report.create_plot(
                    samples, plot=True, save_path=str(Path(__file__).resolve())
                )
            else:
                self.start_refocus_listener()  # Ensures IO1 is low at start; pause/resume comes from Qudi via localhost:6000
                self.is_running = True
                self.job = self.qm.execute(self.HBT_prog)  # start the job
                res_handles = self.job.result_handles
                hist_handle = res_handles.get("histogram")
                total1_handle = res_handles.get("total1")
                total2_handle = res_handles.get("total2")
                total_shots_handle = res_handles.get("total_shots")
                try:
                    hist_handle.wait_for_values(1, timeout=30)
                except TimeoutError as e:
                    print(
                        f"[HBT] Timed out waiting for the first histogram flush from "
                        f"the OPX: {e}. job status={self.job.status}. Aborting "
                        f"start_program()."
                    )
                    try:
                        print(self.job.execution_report())
                    except Exception as report_exc:
                        print(f"[HBT] could not get execution report: {report_exc}")
                    self.is_running = False
                    return

                last_flush_idx = 0

                while res_handles.is_processing() and self.is_running:
                    try:
                        n_flushes = hist_handle.count_so_far()
                        if n_flushes > last_flush_idx:
                            latest = slice(n_flushes - 1, n_flushes)
                            # Each flush is a full cumulative snapshot (computed
                            # on-chip), not a delta - replace, don't accumulate.
                            # Use a length-1 slice (not a bare int index) so the
                            # fetch always returns an array, regardless of
                            # whether the underlying stream is buffered.
                            self.coincidence_hist = hist_handle.fetch(latest)["value"][
                                0
                            ].astype(np.int64)
                            self.total_counts_1 = int(
                                total1_handle.fetch(latest)["value"][0]
                            )
                            self.total_counts_2 = int(
                                total2_handle.fetch(latest)["value"][0]
                            )
                            self.total_windows = int(
                                total_shots_handle.fetch(latest)["value"][0]
                            )
                            last_flush_idx = n_flushes

                            if self.num_windows and self.total_windows >= self.num_windows:
                                self.job.halt()
                                break

                        time.sleep(0.2)  # Small delay to prevent excessive CPU usage
                    except Exception as e:
                        print(f"Error fetching results: {e}")
                        break
        except Exception as e:
            print(f"Error in HBT.start_program: {e}")
            import traceback

            traceback.print_exc()
