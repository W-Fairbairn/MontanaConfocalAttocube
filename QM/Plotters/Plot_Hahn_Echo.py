import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit
from configuration import *

# Load data
f = np.load(save_dir / "2026-04-09/#499_Echo_162742/arrays.npz")
t_vec = f["t_vec"]
counts1 = f["counts1_data"]
counts1_ref = f["counts1_ref_data"]
norm1 = counts1 / counts1_ref

counts2 = f["counts2_data"]
counts2_ref = f["counts2_ref_data"]
norm2 = counts2 / counts2_ref

diff = norm1 - norm2
iteration = 10000000

# Convert time to ns (8 is the factor: x4 for 4ns clock cycle, x2 for two idle times)
x = 8 * t_vec

# Define T2 decay function (exponential decay)
def t2_decay(t, A, T2, C):
    """T2 decay function (exponential decay)"""
    return A * np.exp(- 2*t / T2) + C

# Fit norm1 signal
try:
    popt1, pcov1 = curve_fit(t2_decay, x, norm1, p0=(1, 1000, 0), maxfev=10000)
    A1_fit, T2_1_fit, C1_fit = popt1
    T2_1_err = np.sqrt(np.diag(pcov1))[1]
    fit1_success = True
except Exception as e:
    print(f"Fit 1 failed: {e}")
    fit1_success = False
    T2_1_fit = T2_1_err = 0

# Fit norm2 signal
try:
    popt2, pcov2 = curve_fit(t2_decay, x, norm2, p0=(1, 1000, 0), maxfev=10000)
    A2_fit, T2_2_fit, C2_fit = popt2
    T2_2_err = np.sqrt(np.diag(pcov2))[1]
    fit2_success = True
except Exception as e:
    print(f"Fit 2 failed: {e}")
    fit2_success = False
    T2_2_fit = T2_2_err = 0

# Fit the difference signal to extract T2
try:
    popt, pcov = curve_fit(t2_decay, x, diff, p0=(0.1, 1000, 0), maxfev=10000)
    A_fit, T2_fit, C_fit = popt
    T2_err = np.sqrt(np.diag(pcov))[1]
    fit_success = True
except Exception as e:
    print(f"Fit failed: {e}")
    fit_success = False
    A_fit = T2_fit = C_fit = T2_err = 0

# Create plots matching Hahn_Echo.py
fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 6), sharex=True)

# Plot 1: First sequence (x90 - idle - x180 - idle - x90)
ax1.scatter(x, norm1, label="x90_idle_x180_idle_x90")
if fit1_success:
    t_fit = np.linspace(0, max(x), 500)
    ax1.plot(t_fit, t2_decay(t_fit, *popt1), 'r-',
             label=f'T2 Fit: {T2_1_fit:.0f} ± {T2_1_err:.0f} ns')
ax1.set_ylabel("Norm. Signal")
ax1.set_title("Hahn Echo")
ax1.legend()
ax1.grid(True, alpha=0.3)

# Plot 2: Second sequence (x90 - idle - x180 - idle - -x90)
ax2.scatter(x, norm2, label="x90_idle_x180_idle_-x90")
if fit2_success:
    t_fit = np.linspace(0, max(x), 500)
    ax2.plot(t_fit, t2_decay(t_fit, *popt2), 'r-',
             label=f'T2 Fit: {T2_2_fit:.0f} ± {T2_2_err:.0f} ns')
ax2.set_ylabel("Norm. Signal")
ax2.set_title("Hahn Echo")
ax2.legend()
ax2.grid(True, alpha=0.3)

# Plot 3: Difference signal with T2 fit
ax3.scatter(x, diff, color="black", label="Difference")
if fit_success:
    t_fit = np.linspace(0, max(x), 500)
    ax3.plot(t_fit, t2_decay(t_fit, *popt), 'r-',
             label=f'T2 Fit: {T2_fit:.0f} ± {T2_err:.0f} ns')
ax3.set_xlabel("Hahn echo idle time [ns]")
ax3.set_ylabel("ΔSignal")
ax3.legend()
ax3.grid(True, alpha=0.3)

plt.tight_layout()
plt.show()