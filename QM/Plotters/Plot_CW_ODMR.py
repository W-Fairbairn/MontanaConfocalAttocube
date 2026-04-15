import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit

# Configuration
NUM_DIPS = 2  # Change to fit multiple dips (1, 2, 3, etc.)

# Load data
f = np.load("/MontanaConfocalAttocube/QM/save_dir/2026-03-31/#367_cw_odmr_112736/arrays.npz")
f_vec = f["IF_frequencies"] / 1e6  # MHz
counts = f["counts_data"] / 1000   # kcounts

print(f"Frequency range: {f_vec.min():.1f} to {f_vec.max():.1f} MHz")

# Normalize for fitting
c_min, c_max = counts.min(), counts.max()
counts_norm = (counts - c_min) / (c_max - c_min)

# Lorentzian dip function
def lorentzian(f, *params):
    offset = params[-1]
    y = np.full_like(f, offset, dtype=float)
    for i in range((len(params) - 1) // 3):
        center, width, depth = params[3*i:3*i+3]
        y -= depth / (1 + (4 * (f - center)**2 / width**2))
    return y

# Find dip clusters (group nearby deep points)
# Find points near the minimum value
min_counts = np.min(counts)
threshold = min_counts + (np.max(counts) - min_counts) * 0.2  # 20% above minimum
deep_points = np.where(counts < threshold)[0]

# Cluster nearby points
clusters = []
if len(deep_points) > 0:
    current_cluster = [deep_points[0]]
    for idx in deep_points[1:]:
        if idx - current_cluster[-1] < 5:  # Within 5 indices
            current_cluster.append(idx)
        else:
            clusters.append(current_cluster)
            current_cluster = [idx]
    clusters.append(current_cluster)

# Find center of each cluster
peaks = np.array([int(np.mean(c)) for c in clusters])[:NUM_DIPS]
peaks = np.sort(peaks)

print(f"Found {len(peaks)} dip cluster(s) at MHz: {[f'{f_vec[i]:.1f}' for i in peaks]}")

# Initial guess
p0 = []
if len(peaks) > 0:
    for i in range(min(NUM_DIPS, len(peaks))):
        idx = peaks[i]
        p0.extend([f_vec[idx], 1.0, (c_max - counts[idx]) / (c_max - c_min)])
else:
    # No peaks found, use center of frequency range
    f_center = (f_vec.min() + f_vec.max()) / 2
    depth = (c_max - counts.min()) / (c_max - c_min)
    p0.extend([f_center, 1.0, depth])

# Pad with extra dips if needed
while len(p0) < NUM_DIPS * 3:
    last_center = p0[-3] if len(p0) >= 3 else f_vec.min() + (f_vec.max() - f_vec.min()) / 2
    p0.extend([last_center + 2, 1.0, 0.2])

p0.append(c_min / (c_max - c_min))  # offset

# Fit
try:
    popt, _ = curve_fit(lorentzian, f_vec, counts_norm, p0=p0, maxfev=5000)

    # Print results
    print("\n" + "="*50)
    print(f"Lorentzian Dip Fit ({NUM_DIPS} dip(s))")
    print("="*50)
    n_dips = (len(popt) - 1) // 3
    for i in range(n_dips):
        center, width, depth_norm = popt[3*i:3*i+3]
        depth = depth_norm * (c_max - c_min)
        print(f"\nDip {i+1}:")
        print(f"  Center: {center:.4f} MHz")
        print(f"  Width:  {width:.4f} MHz")
        print(f"  Depth:  {depth:.2f} kcounts")
    offset = (popt[-1] * (c_max - c_min) + c_min)
    print(f"\nOffset: {offset:.2f} kcounts")
    print("="*50 + "\n")
    fit_ok = True
except Exception as e:
    print(f"Fit failed: {e}")
    fit_ok = False

# Plot
plt.figure(figsize=(12, 6))
plt.scatter(f_vec, counts, color='blue', label='Data', s=50)
if fit_ok:
    f_smooth = np.linspace(f_vec.min(), f_vec.max(), 500)
    c_fit = lorentzian(f_smooth, *popt) * (c_max - c_min) + c_min
    plt.plot(f_smooth, c_fit, 'r-', linewidth=2, label='Fit')
plt.xlabel("IF Frequency [MHz]")
plt.ylabel("Counts [kcounts]")
plt.title("CW ODMR")
plt.grid(alpha=0.3)
plt.legend()
plt.tight_layout()
plt.show()

