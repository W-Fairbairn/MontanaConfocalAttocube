"""x90 / -x90 pulse readout sanity check

Minimal script derived from `Hahn_Echo.py`.

Goal
----
Validate that your readout chain (laser + SPCM time-tagging) responds consistently when applying
a +x90 versus a -x90 microwave pulse.

What it does
------------
For each averaging iteration it runs two back-to-back sequences:
  1) init -> x90 -> readout (and reference readout)
  2) init -> -x90 -> readout (and reference readout)

It live-plots:
  - normalized counts for x90 and -x90 (counts / reference)
  - their difference

Notes
-----
- This is *not* a full calibration; it’s just a quick wiring/polarity sanity check.
- If both traces are identical, that can be OK depending on your state-prep and readout model.
  The important thing is stability and that normalization behaves as expected.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from qm import QuantumMachinesManager, SimulationConfig
from qm.qua import *

from configuration import *
from qualang_tools.results import fetching_tool, progress_counter
from qualang_tools.plot import interrupt_on_close
from qualang_tools.results.data_handler import DataHandler

##################
#   Parameters   #
##################
n_avg = 100_000_000  # keep large for stability; stop early by closing the plot

# Use same readout length & time-tagging array size pattern as Hahn_Echo
# (Times array size only limits the number of tags stored, not the measurement length.)
time_arr_len = 100

# Optional: override x90/-x90 pulse lengths from a Rabi frequency (same approach as Hahn_Echo)
# Comment this out if you want to use the values already defined in configuration.py.
rabi_frequency = 10.55 * u.MHz
ODMR_peak_freq = -131 * u.MHz
pi_pulse_len = (1 / (2 * rabi_frequency)) / 1e-9  # ns
config["octaves"][octave]["RF_outputs"][1]["gain"] = 0
print("pi", pi_pulse_len, "ns")
print("pi/2", pi_pulse_len / 2, "ns")
config["pulses"]["x180_pulse"]["length"] = (pi_pulse_len) // 4 * 4
config["pulses"]["x90_pulse"]["length"] = (pi_pulse_len / 2) // 4 * 4
config["pulses"]["-x90_pulse"]["length"] = (pi_pulse_len / 2) // 4 * 4
config["pulses"]["x270_pulse"]["length"] = (pi_pulse_len * 1.5) // 4 * 4


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
    times = declare(int, size=time_arr_len)

    counts_x90_st = declare_stream()
    counts_x90_ref_st = declare_stream()
    counts_mx90_st = declare_stream()
    counts_mx90_ref_st = declare_stream()

    times_st = declare_stream()
    times_ref_st = declare_stream()

    i = declare(int)
    n = declare(int)
    n_st = declare_stream()

    # One-time laser spin init like Hahn_Echo
    play("laser_ON", "AOM2")
    wait(wait_between_runs * u.ns, "AOM2")
    t = 100//4
    update_frequency("NV", ODMR_peak_freq, keep_phase=True)
    with for_(n, 0, n < n_avg, n + 1):
        # --- x90 sequence ---
        #reset_if_phase("NV")  # ensure consistent phase reference for the test, but not strictly necessary for a sanity check
        #update_frequency("NV", ODMR_peak_freq)
        align()
        play("x90" * amp(1), "NV")
        wait(t)
        play("x180" * amp(1), "NV")
        wait(t)
        play("x90" * amp(1), "NV")
        align()
        play("laser_ON", "AOM2")
        measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
        save(counts, counts_x90_st)
        with for_(i, 0, i < counts, i + 1):
            save(times[i], times_st)
        # reference
        measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
        save(counts, counts_x90_ref_st)


        wait(wait_between_runs * u.ns, "AOM2")

        # --- -x90 sequence ---
        #reset_if_phase("NV")
        #update_frequency("NV", ODMR_peak_freq)
        align()
        align()
        play("x90" * amp(1), "NV")
        wait(t)
        play("x180" * amp(1), "NV")
        wait(t)
        play("-x90" * amp(1), "NV")
        align()
          # short wait to ensure the two pulses are not perfectly back-to-back, which can cause issues with some AOMs
        align()
        play("laser_ON", "AOM2")
        measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
        save(counts, counts_mx90_st)
        with for_(i, 0, i < counts, i + 1):
            save(times[i], times_ref_st)
        # reference
        measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
        save(counts, counts_mx90_ref_st)

        wait(wait_between_runs * u.ns, "AOM2")
        save(n, n_st)

    with stream_processing():
        counts_x90_st.average().save("counts_x90")
        counts_x90_ref_st.average().save("counts_x90_ref")
        counts_mx90_st.average().save("counts_mx90")
        counts_mx90_ref_st.average().save("counts_mx90_ref")
        times_st.save_all("time_tags")
        times_ref_st.save_all("time_tags_ref")
        n_st.save("iteration")

#####################################
#  Open Communication with the QOP   #
#####################################
qmm = QuantumMachinesManager(
    host=qop_ip,
    cluster_name=cluster_name,
    octave_calibration_db_path=calibration_db_dir,
)

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
            "counts_x90",
            "counts_x90_ref",
            "counts_mx90",
            "counts_mx90_ref",
            "iteration",
            "time_tags",
            "time_tags_ref",
        ],
        mode="live",
    )

    plt.ion()
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 15), sharex=False)
    interrupt_on_close(fig, job)
    time_tag_arr = np.zeros(meas_len_1)
    time_tag_arr2 = np.zeros(meas_len_1)

    while results.is_processing():
        if not plt.fignum_exists(fig.number):
            break

        (
            counts_x90,
            counts_x90_ref,
            counts_mx90,
            counts_mx90_ref,
            iteration,
            time_tags,
            time_tags_ref,
        ) = results.fetch_all()

        # protect against divide-by-zero during early startup
        if counts_x90_ref == 0 or counts_mx90_ref == 0:
            continue

        norm_x90 = counts_x90 / counts_x90_ref
        norm_mx90 = counts_mx90 / counts_mx90_ref

        diff_x90_mx90 = norm_x90 - norm_mx90

        progress_counter(iteration, n_avg, start_time=results.get_start_time())

        ax1.cla()
        ax1.bar(
            [1, 2],
            [norm_x90, norm_mx90],
            tick_label=["x90,x90", "x90,-x90"],
        )
        ax1.set_ylabel("Normalized counts (counts / ref)")
        ax1.set_title("Microwave pulse readout sanity check")

        ymin = min(norm_x90, norm_mx90)
        ymax = max(norm_x90, norm_mx90)
        if ymin == ymax:
            ax1.set_ylim(ymin * 0.99, ymax * 1.01 if ymax != 0 else 1)
        else:
            ax1.set_ylim(ymin * 0.99, ymax * 1.01)

        ax2.cla()
        ax2.axhline(0.0, color="black", linewidth=1)
        ax2.bar(
            [0],
            [diff_x90_mx90],
            tick_label=["(x90,x90)-(x90,-x90)"],
        )
        ax2.set_ylabel("Δ normalized")

        fig.canvas.draw_idle()
        fig.canvas.flush_events()

        ax3.cla()
        ax3.set_xlabel("Time since readout start [4 ns bins]")
        ax3.set_ylabel("Counts")

        rel_bins = np.asarray(time_tags, dtype=int)
        rel_bins = rel_bins[(rel_bins >= 0) & (rel_bins < meas_len_1)]
        rel_bins2 = np.asarray(time_tags_ref, dtype=int)
        rel_bins2 = rel_bins2[(rel_bins2 >= 0) & (rel_bins2 < meas_len_1)]

        for b in rel_bins:
            time_tag_arr[b] += 1
        for b in rel_bins2:
            time_tag_arr2[b] += 1

        ax3.plot(np.arange(meas_len_1), time_tag_arr, label="Counts x90")
        ax3.plot(np.arange(meas_len_1), time_tag_arr2, color="orange", label="Counts x-90")
        ax3.set_xlabel("Time since readout start [4 ns bins]")
        ax3.set_ylabel("Counts")
        ax3.legend()

        time_tag_arr[:] = 0
        time_tag_arr2[:] = 0

    # Save results snapshot (final values)
    script_name = Path(__file__).name
    data_handler = DataHandler(root_data_folder=save_dir)

    # If loop never fetched, guard
    try:
        save_data_dict.update(
            {
                "counts_x90": counts_x90,
                "counts_x90_ref": counts_x90_ref,
                "counts_mx90": counts_mx90,
                "counts_mx90_ref": counts_mx90_ref,
                "norm_x90": norm_x90,
                "norm_mx90": norm_mx90,
                "diff_x90_mx90": diff_x90_mx90,
            }
        )
    except NameError:
        pass

    data_handler.additional_files = {script_name: script_name, **default_additional_files}
    data_handler.save_data(data=save_data_dict, name="x90_pulse_readout_test")
