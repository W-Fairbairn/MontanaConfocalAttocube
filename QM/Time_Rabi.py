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
#from configuration import *
from qualang_tools.results.data_handler import DataHandler
import time
from scipy.optimize import curve_fit
from experiment_base import *
from settings_dialog_base import SettingsDialogBase


class SettingsDialogRabi(SettingsDialogBase):
    SETTINGS_GROUP = "QM_Rabi"
    WINDOW_TITLE = "Settings"

    SETTINGS_SCHEMA = {
        "time_max": {"label": "Time max (ns):", "default": 500, "type": int},
        "num_points": {"label": "Number of points:", "default": 50, "type": int},
        "num_averages": {"label": "Number of averages:", "default": 10_000_000, "type": int, "spacer_after": True},
        "resonant_Frequency": {"label": "Resonant Frequency (MHz):", "default": 0.0, "type": float},
        "gain": {"label": "Gain:", "default": 15, "type": int},
    }


class Rabi(ExperimentBase):
    def __init__(self):

        self.qmm = None
        self.qm = None
        self.job = None

        ##################
        #   Parameters   #
        ##################
        self.is_running = False
        self.num_points = None
        self.length_run = None
        self.t_vec = None
        self.n_avg = None
        self.time_rabi = None
        self.gain = None
        self.original_rf_gain = None
        self.original_output_mode = None
        self.counts, self.counts_ref, self.iteration, self.time_tags = None, None, None, None

        # Data to save
        self.save_data_dict = {
            "n_avg": self.n_avg,
            "t_vec": self.t_vec,
            "config": config,
        }

    def restore_config(self):
        """Restore the original RF output settings from before compilation."""
        # Restore in-memory config first
        if self.original_output_mode is not None:
            config["octaves"][octave]["RF_outputs"][1]["output_mode"] = self.original_output_mode
        if self.original_rf_gain is not None:
            config["octaves"][octave]["RF_outputs"][1]["gain"] = self.original_rf_gain

        # Best-effort: restore on actual Octave hardware too (if QM is available)
        if self.original_rf_gain is not None and self.qm is not None:
            try:
                self.qm.octave.set_rf_output_gain("NV", self.original_rf_gain)
            except Exception as e:
                print(
                    f"Warning: failed to restore Octave RF output gain for NV to {self.original_rf_gain} dB: {e}"
                )

    def compile_program(self):
        s = SettingsDialogRabi.get_settings()
        freq = float(s["resonant_Frequency"])
        self.length_run = int(s["time_max"])
        self.num_points = int(s["num_points"])
        self.n_avg = int(s["num_averages"])
        self.gain = int(s["gain"])

        # Save original values to restore later so other experiments aren't affected.
        self.original_rf_gain = config["octaves"][octave]["RF_outputs"][1].get("gain")
        self.original_output_mode = config["octaves"][octave]["RF_outputs"][1].get("output_mode")

        # Apply requested gain for this experiment
        config["octaves"][octave]["RF_outputs"][1]["gain"] = self.gain
        self.qmm = QuantumMachinesManager(host=qop_ip, cluster_name=cluster_name,
                                          octave_calibration_db_path=calibration_db_dir)
        self.qm = self.qmm.open_qm(config, close_other_machines=True)

        # Apply gain on the Octave hardware as well (best-effort)
        try:
            self.qm.octave.set_rf_output_gain("NV", self.gain)
        except Exception as e:
            print(f"Warning: failed to set Octave RF output gain for NV to {self.gain} dB: {e}")

        # Clear data arrays from previous runs
        self.counts, self.counts_ref, self.iteration, self.time_tags = None, None, None, None


        self.t_vec = np.arange(4, self.length_run // 4, max(1, self.length_run // (4 * self.num_points)))
        freq = freq * u.MHz  # Hz
        ###################
        # The QUA program #
        ###################
        with program() as self.time_rabi:
            counts = declare(int)  # variable for number of counts
            counts_ref = declare(int)  # variable for number of counts in reference window
            counts_st = declare_stream()  # stream for counts
            counts_ref_st = declare_stream()  # stream for reference counts
            times = declare(int, size=1000)  # QUA vector for storing the time-tags
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
                    update_frequency("NV", freq)
                    align()
                    play("cw" * amp(1), "NV", duration=t)
                    align()  # Play the laser pulse after the mw pulse
                    play("laser_ON", "AOM2")

                    # Signal window
                    measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
                    save(counts, counts_st)  # save counts
                    with for_(i, 0, i < counts, i + 1):
                        save(times[i], times_st)  # cant directly save QUA vector, loop and save each element separately

                    # Reference window
                    measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
                    save(counts, counts_ref_st)
                    wait(wait_between_runs * u.ns)

                save(n, n_st)  # save number of iteration inside for_loop

            with stream_processing():
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
            if self.job is not None:
                self.job.halt()
        except Exception as e:
            print(f"Error halting the job: {e}")
        finally:
            # Ensure config/hardware are restored when stopping
            self.restore_config()

    def save_data(self):
        # Save results
        script_name = Path(__file__).name
        data_handler = DataHandler(root_data_folder=save_dir)
        self.save_data_dict.update({"counts_data": self.counts})
        self.save_data_dict.update({"counts_dark_data": self.counts_ref})
        self.save_data_dict.update({"normalized_data": self.counts / self.counts_ref})
        self.save_data_dict.update({"iteration": np.array([int(self.iteration)])})
        data_handler.save_data(data=self.save_data_dict, name="_".join(script_name.split("_")[1:]).split(".")[0])

    def get_plot_info(self):
        return {
            "x_text": "Time",
            "x_units": "ns",
            "y_text": "Normalised signal",
            "y_units": "arb. units",
        }

    def fit_func(self, t, A, f, T2, phi, C):
        t = t * 1E-9  # Convert to seconds for fitting
        return A * np.exp(-t / T2) * np.sin(2 * np.pi * f * t + phi) + C

    def fit(self):
        x = self.get_x()
        y = self.get_y()
        err = self.get_err()
        A_guess = (np.max(y) - np.min(y)) / 2
        C_guess = np.mean(y)

        # t = time array, y = data
        dt = (x[1] - x[0])*1E-9  # sampling interval
        fs = 1 / dt  # sampling frequency

        Y = np.fft.fft(y)
        freqs = np.fft.fftfreq(len(y), dt)

        # Take only positive frequencies
        mask = freqs > 0
        freqs = freqs[mask]
        power = np.abs(Y[mask])

        # Dominant frequency
        print(freqs)
        f_guess = freqs[np.argmax(power)]
        print(f_guess)

        #f_guess = 7E6  # Initial frequency guess in Hz
        T2_guess = 0.1E-6  # Decay time guess
        phi_guess = 0  # Phase guess

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
        # Always recompile to apply any setting changes
        self.compile_program()
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
                    # Add debug plots here if needed
                    time.sleep(0.01)  # Small sleep to prevent CPU spinning
                self.save_data()
        except Exception as e:
            print(f"Error in start_rabi: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # Always restore original config/hardware settings
            self.restore_config()
