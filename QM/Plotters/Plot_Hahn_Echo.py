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
from MontanaConfocalAttocube.QM.configuration import *

# Load data
f = np.load("../save_dir/2026-11-09/#1537_xy8_153007/arrays.npz")
t_vec = f["t_vec"]
counts1 = f["counts1_data"]
counts1_ref = f["counts1_ref_data"]
norm1 = counts1 / counts1_ref

print(t_vec)

counts2 = f["counts2_data"]
counts2_ref = f["counts2_ref_data"]
norm2 = counts2 / counts2_ref

iteration = f["iteration"][0]
print(iteration)

#norm1 = 1 / norm1
diff = (norm1 - norm2)
#norm1 -= (np.max(norm1) - 1)
#norm2 -= (np.max(norm2) - 1)

# Convert time to ns (8 is the factor: x4 for 4ns clock cycle, x2 for two idle times)
#x = (8 * t_vec)
start_idx = 0
x = (t_vec * 4 * 8 * 10)
diff = diff[start_idx:]
norm1 = norm1[start_idx:]
norm2 = norm2[start_idx:]
x = x[start_idx:]


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

if counts1 is not None and counts1_ref is not None and iteration is not None and counts2 is not None and counts2_ref is not None:
    count1_err = np.sqrt(counts1 * iteration) / iteration
    ref1_err = np.sqrt(counts1_ref * iteration) / iteration
    norm1_err = (counts1 / counts1_ref) * np.sqrt(
        (count1_err / counts1) ** 2 + (ref1_err / counts1_ref) ** 2)

    count2_err = np.sqrt(counts2 * iteration) / iteration
    ref2_err = np.sqrt(counts2_ref * iteration) / iteration
    norm2_err = (counts2 / counts2_ref) * np.sqrt(
        (count2_err / counts2) ** 2 + (ref2_err / counts2_ref) ** 2)

    total_err =  np.sqrt(norm1_err ** 2 + norm2_err ** 2)

count1_err = count1_err[start_idx:]
count2_err = count2_err[start_idx:]
norm1_err = norm1_err[start_idx:]
norm2_err = norm2_err[start_idx:]
total_err = total_err[start_idx:]

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
ax1.errorbar(x, norm1, yerr=norm1_err, label="x90_idle_x180_idle_x90", capsize=2, fmt='.')
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
ax1.errorbar(x, norm2, yerr=norm2_err, label="x90_idle_x180_idle_-x90", capsize=2, fmt='.')
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
ax2.errorbar(x, diff, yerr = total_err, color="black", label="Difference", capsize=2, fmt='.')
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

fig, ax3 = plt.subplots(1,1, figsize=(10, 6))

# Normalize using data-derived endpoint estimates rather than the plain (p=1)
# exponential fit: for ANY stretching exponent p, A*exp(-(t/T2)^p)+C -> C as t->inf
# and -> A+C as t->0, so C and A can be read off the data's plateau and earliest
# points without presupposing a decay shape. This avoids normalizing the data used
# to test p against a fit that already assumed p=1.
tail_n = max(5, int(0.2 * diff.size))
head_n = max(3, int(0.1 * diff.size))

C_est = np.mean(diff[-tail_n:])
sigma_C_est = np.sqrt(np.sum(total_err[-tail_n:] ** 2)) / tail_n

A_plus_C_est = np.mean(diff[:head_n])
sigma_A_plus_C_est = np.sqrt(np.sum(total_err[:head_n] ** 2)) / head_n

A_est = A_plus_C_est - C_est
sigma_A_est = np.sqrt(sigma_A_plus_C_est ** 2 + sigma_C_est ** 2)

y_norm = (diff - C_est) / A_est
sigma_y_norm = np.sqrt(
    (total_err / A_est) ** 2
    + (sigma_C_est / A_est) ** 2
    + (y_norm * sigma_A_est / A_est) ** 2
)

log_x = np.log(x)
log_log_y = np.log(-np.log(np.abs(y_norm)))

# d[ln(-ln(y))]/dy = -1 / (y * ln(y)) -- propagate sigma_y_norm through this derivative.
with np.errstate(divide="ignore", invalid="ignore"):
    d_loglog_dy = 1.0 / np.abs(y_norm * np.log(np.abs(y_norm)))
    sigma_log_log_y = d_loglog_dy * sigma_y_norm

finite_mask = (
    np.isfinite(log_x) & np.isfinite(log_log_y)
    & np.isfinite(sigma_log_log_y) & (sigma_log_log_y > 0)
)

# The log-log transform diverges at BOTH ends of the decay: y_norm -> 1 (small t)
# and y_norm -> 0 (large t, near baseline, where noise can even push y_norm
# slightly negative -- np.abs() would silently turn that into a finite but
# physically meaningless point, since the model requires y > 0). Keep only points
# that are positive and statistically separated from both 0 and 1 by more than
# their own propagated uncertainty; near either boundary a tiny error in y_norm
# maps to a huge, fit-biasing error in ln(-ln(y)).
finite_mask &= (
    (y_norm > 0)
    & (y_norm - sigma_y_norm > 0)
    & (1 - y_norm - sigma_y_norm > 0)
)

ax3.errorbar(
    log_x[finite_mask], log_log_y[finite_mask], yerr=sigma_log_log_y[finite_mask],
    fmt=".", color="black", capsize=2, label="Data",
)
ax3.set_xlabel("ln(t)")
ax3.set_ylabel("ln(-ln(y))")


def _linear(t, m, b):
    return m * t + b


# Weighted linear fit: ln(-ln(y)) = p * ln(t) - p * ln(T2)
if finite_mask.sum() >= 2:
    lin_popt, lin_pcov = curve_fit(
        _linear,
        log_x[finite_mask],
        log_log_y[finite_mask],
        sigma=sigma_log_log_y[finite_mask],
        absolute_sigma=True,
    )
    p_stretch, intercept = lin_popt
    p_err, intercept_err = np.sqrt(np.diag(lin_pcov))
    cov_p_intercept = lin_pcov[0, 1]

    T2_stretch = np.exp(-intercept / p_stretch)
    # Propagate (p, intercept) covariance into T2 = exp(-intercept/p).
    dT2_dp = T2_stretch * intercept / p_stretch ** 2
    dT2_dintercept = -T2_stretch / p_stretch
    T2_stretch_err = np.sqrt(
        (dT2_dp * p_err) ** 2
        + (dT2_dintercept * intercept_err) ** 2
        + 2 * dT2_dp * dT2_dintercept * cov_p_intercept
    )

    x_line = np.linspace(log_x[finite_mask].min(), log_x[finite_mask].max(), 500)
    ax3.plot(
        x_line,
        _linear(x_line, *lin_popt),
        "r-",
        label=(
            f"p = {p_stretch:.2f} ± {p_err:.2f}, "
            f"T2 = {T2_stretch / 1000:.2f} ± {T2_stretch_err / 1000:.2f} µs"
        ),
    )
    ax3.legend()
    print(f"Stretching coefficient p = {p_stretch:.3f} ± {p_err:.3f}")
    print(f"T2 (from linearization) = {T2_stretch:.1f} ± {T2_stretch_err:.1f} ns")
else:
    print("Not enough finite points on the log-log plot for a linear fit.")

plt.tight_layout()
plt.show()
