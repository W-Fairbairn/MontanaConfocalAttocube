"""FFT utility for saved Rabi data (arrays.npz).

This is a small offline analysis helper.

It loads a QUA/qualang_tools DataHandler `arrays.npz` file (like the one produced by `Time_Rabi.py`)
and computes an FFT of the *normalized* signal (counts / counts_ref).

Usage (PowerShell)
------------------
python fft_rabi_npz.py --path "C:\\Users\\attocube\\Documents\\MontanaQudiAttocube\\MontanaConfocalAttocube\\QM\\save_dir\\2026-05-13\\#753_Rabi_132539\\arrays.npz"

Optional args:
  --key-signal         Name of the signal array (default: auto-detect)
  --key-ref            Name of the reference array (default: auto-detect)
  --key-x              Name of the x axis array (default: auto-detect)
  --dt-ns              Sampling period in ns if no x array exists
  --plot               Show plots
  --max-freq-mhz       Limit frequency axis in the FFT plot

Notes
-----
- Auto-detection looks for common keys saved by `Time_Rabi.py`: counts_data, counts_dark_data, normalized_data, t_vec.
- If your arrays use different names, pass explicit keys.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np


def _pick_key(keys: list[str], candidates: list[str]) -> str | None:
    lowered = {k.lower(): k for k in keys}
    for c in candidates:
        if c.lower() in lowered:
            return lowered[c.lower()]
    return None


def _as_1d(a: Any) -> np.ndarray:
    arr = np.asarray(a)
    return np.squeeze(arr)


def load_npz(path: Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=True) as data:
        return {k: data[k] for k in data.files}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--path", type=Path, required=True, help="Path to arrays.npz")
    p.add_argument("--key-signal", type=str, default=None, help="Signal counts key")
    p.add_argument("--key-ref", type=str, default=None, help="Reference counts key")
    p.add_argument("--key-x", type=str, default=None, help="X axis key")
    p.add_argument("--dt-ns", type=float, default=None, help="Sampling period in ns if x is missing")
    p.add_argument("--plot", action="store_true", help="Show plots")
    p.add_argument("--max-freq-mhz", type=float, default=None, help="Limit FFT frequency axis")
    args = p.parse_args()

    arrays = load_npz(args.path)
    keys = list(arrays.keys())

    # Prefer normalized directly if available.
    key_norm = _pick_key(keys, ["normalized_data", "normalized", "norm", "y"])

    key_signal = args.key_signal or _pick_key(keys, ["counts_data", "counts", "signal", "counts_signal"])
    key_ref = args.key_ref or _pick_key(keys, ["counts_dark_data", "counts_ref", "ref", "reference", "counts_reference"])

    key_x = args.key_x or _pick_key(keys, ["t_vec", "x", "time", "t", "tau", "durations"])

    if key_norm is not None:
        y = _as_1d(arrays[key_norm]).astype(float)
    else:
        if key_signal is None or key_ref is None:
            raise SystemExit(
                "Could not auto-detect signal/ref keys. Available keys: "
                + ", ".join(keys)
                + "\nProvide --key-signal and --key-ref."
            )
        sig = _as_1d(arrays[key_signal]).astype(float)
        ref = _as_1d(arrays[key_ref]).astype(float)
        if np.any(ref == 0):
            raise SystemExit("Reference contains zeros; can't normalize safely.")
        y = sig / ref

    # Time axis / sampling
    if key_x is not None:
        x = _as_1d(arrays[key_x]).astype(float)

        # Time_Rabi stores t_vec in clock cycles (4 ns) and later plots t_vec*4.
        # Detect and convert to seconds robustly:
        # - If values look like integers and step ~1-10, assume units of 4 ns.
        # - Otherwise assume x is already ns.
        dx = float(np.median(np.diff(x))) if x.size > 1 else np.nan
        if np.isfinite(dx) and dx <= 20 and np.all(np.isclose(x, np.round(x))):
            t_ns = x * 4.0
        else:
            t_ns = x

        if t_ns.size > 1:
            dt_s = float(np.median(np.diff(t_ns))) * 1e-9
        else:
            if args.dt_ns is None:
                raise SystemExit("Need --dt-ns when x has length 1.")
            dt_s = args.dt_ns * 1e-9
    else:
        if args.dt_ns is None:
            raise SystemExit(
                "No x-axis array found to infer sampling. Provide --dt-ns. Available keys: " + ", ".join(keys)
            )
        dt_s = args.dt_ns * 1e-9
        t_ns = np.arange(y.size) * args.dt_ns

    # Remove DC offset (helps FFT peak visibility)
    y0 = y - np.mean(y)

    # FFT
    n = y0.size
    freqs_hz = np.fft.rfftfreq(n, d=dt_s)
    fft = np.fft.rfft(y0)
    amp = np.abs(fft) / n

    # Find dominant peak (ignore DC bin)
    if amp.size > 1:
        peak_idx = int(np.argmax(amp[1:]) + 1)
        peak_freq_hz = float(freqs_hz[peak_idx])
    else:
        peak_idx = 0
        peak_freq_hz = 0.0

    print(f"Loaded: {args.path}")
    print(f"Keys: {', '.join(keys)}")
    print(f"Using dt = {dt_s * 1e9:.3f} ns, N = {n}")
    print(f"Dominant FFT peak: {peak_freq_hz/1e6:.6f} MHz (bin {peak_idx})")

    # Optional plot
    if args.plot:
        import matplotlib.pyplot as plt

        fig, (ax_t, ax_f) = plt.subplots(2, 1, figsize=(12, 8))

        ax_t.plot(t_ns, y, ".-", markersize=3)
        ax_t.set_xlabel("Time (ns)")
        ax_t.set_ylabel("Normalized counts")
        ax_t.set_title("Rabi trace")

        freqs_mhz = freqs_hz / 1e6
        ax_f.plot(freqs_mhz, amp, "-")
        ax_f.axvline(peak_freq_hz / 1e6, color="red", linewidth=1)
        ax_f.set_xlabel("Frequency (MHz)")
        ax_f.set_ylabel("FFT amplitude (arb.)")
        ax_f.set_title("FFT (DC removed)")
        if args.max_freq_mhz is not None:
            ax_f.set_xlim(0, args.max_freq_mhz)

        fig.tight_layout()
        plt.show()

    # Save a small FFT result next to the input file
    out_path = args.path.with_name("fft_results.npz")
    np.savez(
        out_path,
        dt_s=dt_s,
        t_ns=t_ns,
        y=y,
        y0=y0,
        freqs_hz=freqs_hz,
        amp=amp,
        peak_freq_hz=peak_freq_hz,
        peak_bin=peak_idx,
    )
    print(f"Saved FFT results: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
