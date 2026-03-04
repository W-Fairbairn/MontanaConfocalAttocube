import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit
import scienceplots

plt.style.use(['science','no-latex'])
plt.rcParams.update({'font.size': 24})

f = np.load("C:/Users/attocube/Documents/MontanaQudiAttocube/MontanaConfocalAttocube/JM/save_dir/2026-02-08/#211_T1_220021/arrays.npz")
t_vec = f["t_vec"]
counts = f["counts_data"]
x = 4 * t_vec / 1000000  # Convert to ms
norm = counts / f["counts_ref"]
iteration = f["iteration"][0]
counts_ref = f["counts_ref"]
raw_counts = f["raw_counts"]
raw_counts_ref = f["raw_counts_ref"]
raw_counts = [x[0] for x in raw_counts]
raw_counts_ref = [x[0] for x in raw_counts_ref]

f2 = np.load("C:/Users/attocube/Desktop/Will Stuff/#197_T1_102557/arrays.npz")
counts2 = f2["counts_data"]
t_vec2 = f2["t_vec"]
x2 = 4 * t_vec2 / 1000000  # Convert to ms
iter2 = 1000000
count2_err = np.sqrt(counts2 * iter2) / iter2

print(np.sum(raw_counts, axis=0))
print(counts*iteration - np.sum(raw_counts, axis=0))
print(np.sqrt(counts*iteration))
#print(np.size(raw_counts))
#print(np.average(raw_counts)-counts)
print(iteration)

count_err = np.sqrt(counts * iteration) / iteration
ref_err = np.sqrt(counts_ref * iteration) / iteration
norm_err = norm * np.sqrt((count_err / counts) ** 2 + (ref_err / counts_ref) ** 2)

y = norm
err = norm_err
x = x
def decay_func(t, A, T1, C):
    return A * np.exp(-t / T1) + C

def multi_exp_decay_func(t, A1, T1_1, A2, T1_2, C):
    return A1 * np.exp(-t / T1_1) + A2 * np.exp(-t / T1_2) + C

popt: object
popt, pcov = curve_fit(decay_func, x, y, p0=(100, 1, 10), sigma=err, absolute_sigma=True)
A_fit, T1_fit, C_fit = popt
T1_err = np.sqrt(np.diag(pcov))[1]

popt2: object
popt2, pcov2 = curve_fit(decay_func, x2, counts2, p0=(100, 1, 10), sigma=count2_err, absolute_sigma=True)
A_fit2, T1_fit2, C_fit2 = popt2
T1_2_err = np.sqrt(np.diag(pcov2))[1]


norm1 = np.max(y)
norm2 = np.max(counts2)
t_fit = np.linspace(0, max(x), 500)
fig, (ax1) = plt.subplots(1)
ax1.errorbar(x, y/norm1, label="Counts without leakage", yerr=err, capsize=2, fmt='.', color='red')
ax1.plot(t_fit, decay_func(t_fit, *popt)/norm1, 'r-', label=f'T1 = {T1_fit:.2f} ± {T1_err:.2f} ms')
ax1.errorbar(x2, counts2/norm2, label="Counts with leakage", yerr=count2_err, capsize=2, fmt='.', color='blue')
ax1.plot(t_fit, decay_func(t_fit, *popt2)/norm2, 'b-', label=f'T1 = {T1_fit2:.2f} ± {T1_2_err:.2f} ms')
ax1.set_ylabel("Normalised Signal [arb. units]")
ax1.set_title("T1 Decay")
ax1.set_xlabel("Wait time [ms]")
handles, labels = plt.gca().get_legend_handles_labels()
order = [3,1,2,0]
plt.legend([handles[idx] for idx in order],[labels[idx] for idx in order])


plt.show()