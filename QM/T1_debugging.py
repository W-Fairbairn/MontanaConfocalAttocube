
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from qm import QuantumMachinesManager, SimulationConfig
from qm.qua import *

from configuration import *
from qualang_tools.results import fetching_tool, progress_counter
from qualang_tools.plot import interrupt_on_close
from qualang_tools.results.data_handler import DataHandler


def enable_calibration_db_caching(qmm):
    """
    QM's Octave CalibrationDB is backed by a plain TinyDB JSONStorage with no
    read caching: every single internal lookup (get_if_cal, _query_mode, etc.)
    re-reads and re-parses the entire calibration_db.json file from disk. Once
    enough calibration entries accumulate for a given (octave, LO, gain), this
    makes open_qm() take tens of seconds. Wrapping the storage in tinydb's
    CachingMiddleware makes it read the file once (per QuantumMachinesManager
    instance) instead of once per lookup. Call after creating self.qmm and
    before self.qmm.open_qm(...).
    """
    from tinydb import TinyDB
    from tinydb.storages import JSONStorage
    from tinydb.middlewares import CachingMiddleware

    octave_config = getattr(qmm, "_octave_config", None)
    calibration_db = getattr(octave_config, "calibration_db", None) if octave_config else None
    if calibration_db is None:
        return

    db = getattr(calibration_db, "_db", None)
    if db is None or isinstance(db.storage, CachingMiddleware):
        return

    db.close()
    calibration_db._db = TinyDB(
        calibration_db._file_path, indent=4, separators=(",", ": "), storage=CachingMiddleware(JSONStorage)
    )


##################
#   Parameters   #
##################
n_avg = 1_000_000_000  # keep large for stability; stop early by closing the plot

# Use same readout length & time-tagging array size pattern as Hahn_Echo
# (Times array size only limits the number of tags stored, not the measurement length.)
time_arr_len = 1000

# Optional: override x90/-x90 pulse lengths from a Rabi frequency (same approach as Hahn_Echo)
# Comment this out if you want to use the values already defined in configuration.py.
rabi_frequency = 10.44 * u.MHz
ODMR_peak_freq = 128.41 * u.MHz
pi_pulse_len = (1 / (2 * rabi_frequency)) / 1e-9  # ns
config["octaves"][octave]["RF_outputs"][1]["gain"] = 0
print("pi", pi_pulse_len, "ns")
print("pi/2", pi_pulse_len / 2, "ns")
config["pulses"]["x180_pulse"]["length"] = (pi_pulse_len) // 4 * 4
config["pulses"]["x90_pulse"]["length"] = (pi_pulse_len / 2) // 4 * 4
config["pulses"]["-x90_pulse"]["length"] = (pi_pulse_len / 2) // 4 * 4
config["pulses"]["x270_pulse"]["length"] = (pi_pulse_len * 1.5) // 4 * 4

t = 100 // 4  # free-evolution delay, in 4ns clock cycles (100 ns total)
t2 = 1_000_000_000 // 4



# Data to save
save_data_dict = {
    "n_avg": n_avg,
    "config": config,
}

###################
# The QUA program  #
###################
with program() as x90_test:
    counts = declare(int)
    counts2 = declare(int)
    times = declare(int, size=time_arr_len)
    times2 = declare(int, size=time_arr_len)

    counts_ref = declare(int)
    counts2_ref = declare(int)

    times_ref = declare(int, size=time_arr_len)
    times2_ref = declare(int, size=time_arr_len)

    counts_st = declare_stream()
    counts2_st = declare_stream()
    counts_ref_st = declare_stream()
    counts2_ref_st = declare_stream()

    times_st = declare_stream()
    times2_st = declare_stream()
    times_ref_st = declare_stream()
    times2_ref_st = declare_stream()

    i = declare(int)
    n = declare(int)
    n_st = declare_stream()

    # One-time laser spin init like Hahn_Echo
    play("laser_ON", "AOM2")
    wait(wait_between_runs * u.ns, "AOM2")
    update_frequency("NV", ODMR_peak_freq, keep_phase=True)
    with for_(n, 0, n < n_avg, n + 1):
        #play("laser_ON", "AOM2")
        align()
        wait(t)  # wait the variable delay (in clock cycles)
        align()
        play("laser_ON", "AOM2")  # laser on for readout
        measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
        save(counts, counts_st)
        measure("readout", "SPCM1", time_tagging.analog(times_ref, meas_len_1, counts_ref))
        save(counts_ref, counts_ref_st)  # save ref counts
        with for_(i, 0, i < counts, i + 1):
            with if_(i < time_arr_len):
                save(times[i], times_st)

        wait(wait_between_runs * u.ns, "AOM2")

        align()
        wait(t2)  # wait the variable delay (in clock cycles)
        align()
        play("laser_ON", "AOM2")  # laser on for readout
        measure("readout", "SPCM1", time_tagging.analog(times2, meas_len_1, counts2))
        save(counts2, counts2_st)
        measure("readout", "SPCM1", time_tagging.analog(times2_ref, meas_len_1, counts2_ref))
        save(counts2_ref, counts2_ref_st)  # save ref counts
        with for_(i, 0, i < counts2, i + 1):
            with if_(i < time_arr_len):
                save(times2[i], times2_st)

        wait(wait_between_runs * u.ns, "AOM2")

        save(n, n_st)

    with stream_processing():
        counts_st.save_all("counts")
        counts2_st.save_all("counts2")
        counts_ref_st.save_all("counts_ref")
        counts2_ref_st.save_all("counts2_ref")
        times_st.save_all("time_tags")
        times2_st.save_all("time_tags2")
        n_st.save("iteration")

#####################################
#  Open Communication with the QOP   #
#####################################
qmm = QuantumMachinesManager(
    host=qop_ip,
    cluster_name=cluster_name,
    octave_calibration_db_path=calibration_db_dir,
)
enable_calibration_db_caching(qmm)
simulate = False

if simulate:
    job = qmm.simulate(config, x90_test, SimulationConfig(duration=10_000))
    samples = job.get_simulated_samples()
    samples.con1.plot()
    plt.show(block=True)
else:
    qm = qmm.open_qm(config, close_other_machines=True)
    job = qm.execute(x90_test)

    results = fetching_tool(
        job,
        data_list=[
            "counts",
            "counts2",
            "counts_ref",
            "counts2_ref",
            "iteration",
            "time_tags",
            "time_tags2",
        ],
        mode="live",
    )

    plt.ion()
    fig, (ax3) = plt.subplots(1, 1, figsize=(10, 15), sharex=False)
    interrupt_on_close(fig, job)
    time_tag_arr = np.zeros(meas_len_1)
    time_tag_arr2 = np.zeros(meas_len_1)

    while results.is_processing():
        if not plt.fignum_exists(fig.number):
            break
        (
            counts,
            counts2,
            counts_ref,
            counts2_ref,
            iteration,
            time_tags,
            time_tags2,
        ) = results.fetch_all()



        #progress_counter(iteration, n_avg, start_time=results.get_start_time())

        fig.canvas.draw_idle()
        fig.canvas.flush_events()

        ax3.cla()
        ax3.set_xlabel("Time since readout start [4 ns bins]")
        ax3.set_ylabel("Counts")

        rel_bins = np.asarray(time_tags, dtype=int)
        rel_bins = rel_bins[(rel_bins >= 0) & (rel_bins < meas_len_1)]

        rel_bins2 = np.asarray(time_tags2, dtype=int)
        rel_bins2 = rel_bins2[(rel_bins2 >= 0) & (rel_bins2 < meas_len_1)]

        for b in rel_bins:
            time_tag_arr[b] += 1

        for b in rel_bins2:
            time_tag_arr2[b] += 1

        ax3.plot(np.arange(meas_len_1), time_tag_arr, label="Counts t=" + str(t * 4) + " ns")
        ax3.plot(np.arange(meas_len_1), time_tag_arr2, color="orange", label="Counts t=" + str(t2 * 4) + " ns")
        ax3.set_xlabel("Time since readout start [4 ns bins]")
        ax3.set_ylabel("Counts")
        ax3.legend()

        time_tag_arr[:] = 0
        time_tag_arr2[:] = 0

        #print("running")
        plt.show()

    # Save results snapshot (final values)
    script_name = Path(__file__).name
    data_handler = DataHandler(root_data_folder=save_dir)
    data_handler.additional_files = {script_name: script_name, **default_additional_files}
    data_handler.save_data(data=save_data_dict, name="x90_pulse_readout_test")
