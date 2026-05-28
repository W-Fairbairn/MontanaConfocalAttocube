# MontanaConfocalAttocube/QM/Plot_Hahn_Echo.py

import os
import sys
import inspect

currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)
sys.path.insert(0, parentdir)
import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit
from configuration import *

# Load data
f = np.load("save_dir/2026-05-21/#898_Echo_Standalone_143101/arrays.npz")
t_vec = f["t_vec"]
counts1 = f["counts1_data"]
counts1_ref = f["counts1_ref_data"]
norm1 = counts1 / counts1_ref

counts2 = f["counts2_data"]
counts2_ref = f["counts2_ref_data"]
norm2 = counts2 / counts2_ref

iteration = f["iteration"][0]

#norm1 = 1 / norm1
diff = (norm1 - norm2)
#norm1 -= (np.max(norm1) - 1)
#norm2 -= (np.max(norm2) - 1)

# Convert time to ns (8 is the factor: x4 for 4ns clock cycle, x2 for two idle times)
x = (8 * t_vec)
diff = diff[0:]
norm1 = norm1[0:]
norm2 = norm2[0:]
x = x[0:]


# Define T2 decay function (plain exponential decay)
def t2_decay(t, A, T2, C):
    """T2 decay function (single exponential).

    Model: A * exp(-(t/T2)) + C

    Notes:
      - T2 must be > 0
    """
    t = np.asarray(t)
    T2 = np.clip(T2, 1e-12, np.inf)
    return A * np.exp(-(t / T2)) + C


# Common fit settings
_bounds = ([-np.inf, 0.0, -np.inf], [np.inf, np.inf, np.inf])

# Ensure these are defined even if a fit fails
popt1 = pcov1 = None
popt2 = pcov2 = None
popt = pcov = None

# Fit norm1 signal
try:
    popt1, pcov1 = curve_fit(
        t2_decay,
        x,
        norm1,
        p0=(1, 500000, 1),
        bounds=_bounds,
        maxfev=20000,
    )
    A1_fit, T2_1_fit, C1_fit = popt1
    perr1 = np.sqrt(np.diag(pcov1))
    T2_1_err = perr1[1]
    fit1_success = True
except Exception as e:
    print(f"Fit 1 failed: {e}")
    fit1_success = False
    T2_1_fit = T2_1_err = 0

# Fit norm2 signal
try:
    popt2, pcov2 = curve_fit(
        t2_decay,
        x,
        norm2,
        p0=(1, 500000, 1),
        bounds=_bounds,
        maxfev=20000,
    )
    A2_fit, T2_2_fit, C2_fit = popt2
    perr2 = np.sqrt(np.diag(pcov2))
    T2_2_err = perr2[1]
    fit2_success = True
except Exception as e:
    print(f"Fit 2 failed: {e}")
    fit2_success = False
    T2_2_fit = T2_2_err = 0

# Fit the difference signal to extract T2
try:
    x_arr = np.asarray(x)
    y_arr = np.asarray(diff)

    if x_arr.size < 5:
        raise ValueError("Not enough points to fit diff.")

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
        t2_decay,
        x_arr,
        y_arr,
        p0=(A0, T20, C0),
        bounds=_bounds,
        maxfev=50000,
    )
    A_fit, T2_fit, C_fit = popt
    perr = np.sqrt(np.diag(pcov))
    T2_err = perr[1]
    fit_success = True
except Exception as e:
    print(f"Fit failed: {e}")
    fit_success = False
    A_fit = T2_fit = C_fit = T2_err = 0

# Create plots matching Hahn_Echo.py
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)

# Plot 1: First sequence (x90 - idle - x180 - idle - x90)
ax1.scatter(x, norm1, label="x90_idle_x180_idle_x90")
if fit1_success and popt1 is not None:
    t_fit = np.linspace(0, max(x), 500)
    ax1.plot(
        t_fit,
        t2_decay(t_fit, *popt1),
        "r-",
        label=f"T2 Fit: {T2_1_fit:.0f} ± {T2_1_err:.0f} ns",
    )
ax1.set_ylabel("Norm. Signal")
ax1.set_title("Hahn Echo")

ax1.grid(True, alpha=0.3)

# Plot 2: Second sequence (x90 - idle - x180 - idle - -x90)
ax1.scatter(x, norm2, label="x90_idle_x180_idle_-x90")
if fit2_success and popt2 is not None:
    t_fit = np.linspace(0, max(x), 500)
    ax1.plot(
        t_fit,
        t2_decay(t_fit, *popt2),
        "r-",
        label=f"T2 Fit: {T2_2_fit:.0f} ± {T2_2_err:.0f} ns",
    )

ax1.legend()

# Plot 3: Difference signal with T2 fit
ax2.scatter(x, diff, color="black", label="Difference")
if fit_success and popt is not None:
    t_fit = np.linspace(0, max(x), 500)
    ax2.plot(
        t_fit,
        t2_decay(t_fit, *popt),
        "r-",
        label=f"T2 Fit: {T2_fit:.0f} ± {T2_err:.0f} ns",
    )
ax2.set_xlabel("Hahn echo idle time [ns]")
ax2.set_ylabel("ΔSignal")
ax2.legend()
ax2.grid(True, alpha=0.3)

plt.tight_layout()
plt.show()
