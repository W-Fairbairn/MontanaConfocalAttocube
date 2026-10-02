import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit
from MontanaConfocalAttocube.QM.configuration import *
from scipy.fft import fft

#from MontanaConfocalAttocube.QM.configuration import save_dir

f = np.load(save_dir / "2026-09-28/#1433_T1_100959/arrays.npz")
t_vec = f["t_vec"]
counts = f["counts_data"]
x = 4 * t_vec / 1000000  # Convert to ms
norm = counts / f["counts_ref"]
iteration = f["iteration"][0]
counts_ref = f["counts_ref"]

try:
    counts_mw = f["counts_mw"]
    counts_mw_ref = f["counts_mw_ref"]
    mw = True
except:
    mw = False

#print(np.sqrt(counts*iteration))
#print(np.size(raw_counts))
#print(np.average(raw_counts)-counts)
print(iteration)

count_err = np.sqrt(counts * iteration) / iteration
ref_err = np.sqrt(counts_ref * iteration) / iteration
norm_err = norm * np.sqrt((count_err / counts) ** 2 + (ref_err / counts_ref) ** 2)

if mw:
    norm_mw = counts_mw / counts_mw_ref
    count_mw_err = np.sqrt(counts_mw * iteration) / iteration
    ref_mw_err = np.sqrt(counts_mw_ref * iteration) / iteration
    norm_mw_err = norm_mw * np.sqrt((count_mw_err / counts_mw) ** 2 + (ref_mw_err / counts_mw_ref) ** 2)
    y_mw = norm_mw
    err_mw = norm_mw_err
    x_mw = x


y = norm
err = norm_err
x = x
def decay_func(t, A, T1, C):
    return 0.2 * np.exp(-t / T1) + 0.85

def multi_exp_decay_func(t, A1, T1_1, A2, T1_2, C):
    return A1 * np.exp(-t / T1_1) + A2 * np.exp(-t / T1_2) + C


popt: object
popt, pcov = curve_fit(decay_func, x, y, p0=(0.2, 10, 0.85), sigma=err, absolute_sigma=True)
A_fit, T1_fit, C_fit = popt
print(A_fit, T1_fit, C_fit)
T1_err = np.sqrt(np.diag(pcov))[1]

plt.rcParams.update({'font.size': 20})

fig, (ax1) = plt.subplots(1)
ax1.errorbar(x, y, label="counts", yerr=err, capsize=2, fmt='.')
t_fit = np.linspace(0, max(x), 500)
ax1.plot(t_fit, decay_func(t_fit, *popt), 'r-', label=f'Fit: T1 = {T1_fit:.2f} ± {T1_err:.2f} ms')
ax1.set_ylabel("Signal")
ax1.set_title("T1 Decay without mw")
ax1.set_xlabel("Wait time [ms]")
ax1.legend()

'''
def sin(t, A, f, phi):
    return A * np.sin(2 * np.pi * f * t + phi)

residuals = decay_func(x, *popt) - y
popt, pcov = curve_fit(sin, x, residuals)
A_fit, f_fit, phi_fit = popt
'''
if mw:
    popt: object
    popt, pcov = curve_fit(decay_func, x_mw, y_mw, p0=(100, 1, 10), sigma=err_mw, absolute_sigma=True)
    A_fit, T1_fit, C_fit = popt
    T1_err = np.sqrt(np.diag(pcov))[1]

    fig2, (ax2) = plt.subplots(1)
    ax1.errorbar(x_mw, y_mw, label="counts", yerr=err_mw, capsize=2, fmt='.')
    t_fit = np.linspace(0, max(x_mw), 500)
    ax1.plot(t_fit, decay_func(t_fit, *popt), 'r-', label=f'Fit: T1 = {T1_fit:.2f} ± {T1_err:.2f} ms')
    ax2.set_ylabel("Signal")
    ax2.set_title("T1 Decay with mw")
    ax2.set_xlabel("Wait time [ms]")
    ax2.legend()

plt.show()