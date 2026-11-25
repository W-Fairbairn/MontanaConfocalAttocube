"""x180 pulse error-amplification test

Layout derived from `x90_pulse_readout_test.py`.

Goal
----
Estimate x180 pulse fidelity by repeatedly applying the pulse an even number of times
(2*N, for N = 1 .. N_max) and watching how far the readout drifts away from the N=0
(no-MW) baseline. Since each pair of x180 pulses should ideally return the NV to its
initial (ms=0) state, any growing deviation as a function of N is a direct signature of
accumulated pulse error (amplitude/phase/length miscalibration).

What it does
------------
For each averaging iteration it runs, for every N in N_vec:
  1) init -> (x180 x 2N) -> readout (and reference readout)
and once per iteration it also runs a no-MW baseline (init -> readout, reference readout)
to use as the "ideal" reference point (N=0).

It live-plots:
  - normalized counts (counts / reference) vs N, with the no-MW baseline as a horizontal line
  - the deviation of each N point from the no-MW baseline, i.e. the pulse-error signal

Notes
-----
- This is *not* a full randomized-benchmarking-style fidelity measurement; it's a quick,
  deterministic error-amplification sanity check.
- A flat deviation trace (~0 for all N) indicates good x180 calibration. A trace that grows
  with N indicates miscalibrated amplitude/length (over/under-rotation accumulates each pair).
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from qm import QuantumMachinesManager, SimulationConfig
from qm.qua import *

from configuration import *
from qualang_tools.loops import from_array
from qualang_tools.results import fetching_tool, progress_counter
from qualang_tools.plot import interrupt_on_close
from qualang_tools.results.data_handler import DataHandler

##################
#   Parameters   #
##################
n_avg = 100_000_000  # keep large for stability; stop early by closing the plot

# Use same readout length & time-tagging array size pattern as Hahn_Echo / x90 test
time_arr_len = 100

# N sweep: each point plays the x180 pulse 2*N times back-to-back
N_max = 1000
N_step = 100
N_vec = np.arange(1, N_max + 1, N_step)

# Override x180 pulse length from a Rabi frequency (same approach as x90_pulse_readout_test)
# Comment this out if you want to use the value already defined in configuration.py.
rabi_frequency = 7.21 * u.MHz
ODMR_peak_freq = 64.13 * u.MHz
pi_pulse_len = (1 / (2 * rabi_frequency)) / 1e-9  # ns
config["octaves"][octave]["RF_outputs"][1]["gain"] = 0
print("pi", pi_pulse_len, "ns")
config["pulses"]["x180_pulse"]["length"] = (pi_pulse_len) // 4 * 4

# Data to save
save_data_dict = {
    "n_avg": n_avg,
    "N_vec": N_vec,
    "config": config,
}

###################
# The QUA program  #
###################
with program() as x180_error_test:
    counts = declare(int)
    times = declare(int, size=time_arr_len)

    counts_nomw_st = declare_stream()
    counts_nomw_ref_st = declare_stream()
    counts_st = declare_stream()
    counts_ref_st = declare_stream()

    N = declare(int)
    k = declare(int)
    n = declare(int)
    n_st = declare_stream()

    # One-time laser spin init like Hahn_Echo / x90 test
    play("laser_ON", "AOM2")
    wait(wait_between_runs * u.ns, "AOM2")
    update_frequency("NV", ODMR_peak_freq, keep_phase=True)

    with for_(n, 0, n < n_avg, n + 1):
        # --- no MW baseline (N = 0 reference point) ---
        align()
        play("laser_ON", "AOM2")
        measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
        save(counts, counts_nomw_st)
        # reference
        measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
        save(counts, counts_nomw_ref_st)

        wait(wait_between_runs * u.ns, "AOM2")

        # --- x180 error-amplification sweep: play x180 2*N times, for each N in N_vec ---
        with for_(*from_array(N, N_vec)):
            align()
            with for_(k, 0, k < 2 * N, k + 1):
                play("x180" * amp(1), "NV")
            align()
            play("laser_ON", "AOM2")
            measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
            save(counts, counts_st)
            # reference
            measure("readout", "SPCM1", time_tagging.analog(times, meas_len_1, counts))
            save(counts, counts_ref_st)

            wait(wait_between_runs * u.ns, "AOM2")

        save(n, n_st)

    with stream_processing():
        counts_nomw_st.average().save("counts_nomw")
        counts_nomw_ref_st.average().save("counts_nomw_ref")
        counts_st.buffer(len(N_vec)).average().save("counts_x180N")
        counts_ref_st.buffer(len(N_vec)).average().save("counts_x180N_ref")
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
    job = qmm.simulate(config, x180_error_test, SimulationConfig(duration=10_000))
    samples = job.get_simulated_samples()
    samples.con1.plot()
    plt.show(block=True)
else:
    qm = qmm.open_qm(config, close_other_machines=True)
    job = qm.execute(x180_error_test)

    results = fetching_tool(
        job,
        data_list=[
            "counts_nomw",
            "counts_nomw_ref",
            "counts_x180N",
            "counts_x180N_ref",
            "iteration",
        ],
        mode="live",
    )

    plt.ion()
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 10), sharex=True)
    interrupt_on_close(fig, job)

    while results.is_processing():
        if not plt.fignum_exists(fig.number):
            break

        (
            counts_nomw,
            counts_nomw_ref,
            counts_x180N,
            counts_x180N_ref,
            iteration,
        ) = results.fetch_all()

        # protect against divide-by-zero during early startup
        if counts_nomw_ref == 0 or np.any(counts_x180N_ref == 0):
            continue

        norm_nomw = counts_nomw / counts_nomw_ref
        norm_x180N = counts_x180N / counts_x180N_ref

        deviation = norm_x180N - norm_nomw

        progress_counter(iteration, n_avg, start_time=results.get_start_time())

        ax1.cla()
        ax1.plot(N_vec, norm_x180N, "o-", label="x180 x 2N")
        ax1.axhline(norm_nomw, color="black", linestyle="--", label="no MW (N=0)")
        ax1.set_ylabel("Normalized counts (counts / ref)")
        ax1.set_title("x180 pulse error amplification (2N repetitions)")
        ax1.legend()

        ax2.cla()
        ax2.axhline(0.0, color="black", linewidth=1)
        ax2.plot(N_vec, deviation, "o-", color="tab:red")
        ax2.set_xlabel("N (number of x180 pairs, total pulses = 2N)")
        ax2.set_ylabel("Δ normalized vs no-MW")

        fig.canvas.draw_idle()
        fig.canvas.flush_events()

    # Save results snapshot (final values)
    script_name = Path(__file__).name
    data_handler = DataHandler(root_data_folder=save_dir)

    # If loop never fetched, guard
    try:
        save_data_dict.update(
            {
                "counts_nomw": counts_nomw,
                "counts_nomw_ref": counts_nomw_ref,
                "counts_x180N": counts_x180N,
                "counts_x180N_ref": counts_x180N_ref,
                "norm_nomw": norm_nomw,
                "norm_x180N": norm_x180N,
                "deviation": deviation,
                "iteration": iteration,
            }
        )
    except NameError:
        pass

    data_handler.save_data(data=save_data_dict, name="x180_pulse_error_test")
