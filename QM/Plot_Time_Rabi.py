import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit
from configuration import *

plt.rcParams.update({'font.size': 20})

f = np.load(save_dir / "2026-04-09/#489_Rabi_GUI_133336/arrays.npz")
t_vec = f["t_vec"]
counts = f["counts_data"]
counts_ref = f["counts_dark_data"]
x = 4 * t_vec  # Convert to ns
norm = counts / counts_ref
iteration = f["iteration"][0]

count_err = np.sqrt(counts * iteration) / iteration
ref_err = np.sqrt(counts_ref * iteration) / iteration
norm_err = norm * np.sqrt((count_err / counts) ** 2 + (ref_err / counts_ref) ** 2)

y = norm
y = y / np.max(y)
err = norm_err
#x = x[10:]  # Skip the first few points where the signal is very low and noisy
#y = y[10:]
#err = err[10:]

# Define damped sinusoidal function
def damped_sine(t, A, f, T2, phi, C, b):
    t = t*1E-9  # Convert to seconds for fitting
    return A * np.exp(-(t / T2)**b) * np.sin(2 * np.pi * f * t + phi) + C

A_guess = (np.max(y) - np.min(y)) / 2
C_guess = np.mean(y)
f_guess = 7E6  # Initial frequency guess in MHz
T2_guess = 0.5E-6  # Decay time guess
phi_guess = np.pi/2  # Phase guess
b_guess = 1

p0 = [A_guess, f_guess, T2_guess, phi_guess, C_guess, b_guess]
popt, pcov = curve_fit(damped_sine, x, y, p0=p0, sigma=err, absolute_sigma=True, maxfev=5000)
A_fit, f_fit, T2_fit, phi_fit, C_fit, b_fit = popt
print(b_fit)
perr = np.sqrt(np.diag(pcov))
A_err, f_err, T2_err, phi_err, C_err, b_err = perr

fig, (ax1) = plt.subplots(1, figsize=(12, 6))
ax1.errorbar(x, y, label="Counts", yerr=err, capsize=2, fmt='.')
t_fit = np.linspace(0, max(x), 500)
ax1.plot(t_fit, damped_sine(t_fit, *popt), 'r-',
         label=f'T2 = {T2_fit/1E-6:.2f} ± {T2_err/1E-6:.2f} us,\nf = {f_fit/1E6:.2f} ± {f_err/1E6:.2f} MHz')
ax1.set_ylabel("Normalized Signal")
ax1.set_title("Time Rabi Oscillations")
ax1.set_xlabel("Pulse Duration [ns]")
ax1.legend()
ax1.grid(True, alpha=0.3)

plot_ref = False
if plot_ref:
    # Plot 2: Reference counts
    fig2, (ax2) = plt.subplots(1, figsize=(12, 6))
    ax2.errorbar(4 * t_vec / 1000, counts_ref, yerr=ref_err, capsize=2, fmt='o')
    ax2.set_ylabel("Signal")
    ax2.set_title("Reference Counts")
    ax2.set_xlabel("Pulse Duration [µs]")
    ax2.grid(True, alpha=0.3)

plt.show()
