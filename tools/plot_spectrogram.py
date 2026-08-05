"""Plot a spectrogram of an accelerometer log recorded by src/accellogger.py.

Usage:
    python tools/plot_spectrogram.py path/to/accel/0001.csv
    python tools/plot_spectrogram.py 0001.csv --axis z --seg-len 512 -o out.png
"""

import argparse
import os

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy.signal as sg


# MicroPython's time.ticks_ms() wraps at 2**30 ms on the ESP32
TICKS_WRAP = 1 << 30

# Sample intervals longer than this are treated as gaps rather than jitter.
# The logger stalls for 1-3 s while dumping the pre-trigger ring buffer.
GAP_THRESHOLD = 0.05     # s

# Gravity and slow tilt drift are removed before the transform, otherwise the
# DC component leaks through the window sidelobes and raises the noise floor
HIGHPASS_CUTOFF = 1.0    # Hz

# State IDs written by src/main.py
STATE_NAMES = {1: 'IDLE', 2: 'WASHING', 3: 'NOTIFYING', 4: 'UNLOADING'}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv', help='CSV file written by accellogger.py')
    parser.add_argument('--fs', type=float, default=100.0,
                        help='nominal sampling frequency in Hz (default: 100)')
    parser.add_argument('--axis', default='magnitude',
                        choices=['magnitude', 'x', 'y', 'z'],
                        help='signal to analyse; "magnitude" is the norm of '
                             'the three axes and does not depend on how the '
                             'M5Stack is oriented (default: magnitude)')
    parser.add_argument('--seg-len', type=int, default=256,
                        help='STFT window length in samples; longer windows '
                             'trade time resolution for frequency resolution '
                             '(default: 256)')
    parser.add_argument('--hop', type=int, default=64,
                        help='STFT step in samples (default: 64, i.e. 75%% '
                             'overlap at the default window length)')
    parser.add_argument('--dynamic-range', type=float, default=60.0,
                        help='colour scale span below the peak, in dB '
                             '(default: 60)')
    parser.add_argument('--cmap', default='viridis',
                        help='matplotlib colormap (default: viridis)')
    parser.add_argument('-o', '--output',
                        help='write the figure to this file instead of '
                             'showing it interactively')
    return parser.parse_args()


def elapsed_seconds(ticks):
    """Convert the ticks_ms column into a monotonic time axis in seconds.

    ticks_ms wraps around, so consecutive samples are differenced the way
    time.ticks_diff() does before being accumulated.
    """
    half = TICKS_WRAP >> 1
    deltas = ((np.diff(ticks) + half) % TICKS_WRAP - half) / 1000.0
    return np.concatenate(([0.0], np.cumsum(deltas))), deltas


def report_sampling(elapsed, deltas):
    """Print how closely the log matches the nominal sampling rate."""
    median = np.median(deltas)
    print('samples:       {}'.format(deltas.size + 1))
    print('duration:      {:.1f} s'.format(elapsed[-1]))
    print('median period: {:.2f} ms -> {:.2f} Hz'.format(
        median * 1000, 1.0 / median))
    if np.any(deltas <= 0):
        print('WARNING: non-monotonic timestamps, results are unreliable')
    gaps = np.flatnonzero(deltas > GAP_THRESHOLD)
    print('gaps > {:.0f} ms: {}'.format(GAP_THRESHOLD * 1000, gaps.size))
    for i in gaps:
        print('  t = {:8.1f} s  ({:.2f} s missing)'.format(
            elapsed[i], deltas[i]))
    return gaps


def resample(elapsed, frame, fs):
    """Interpolate the axes onto a uniform grid, as the FFT requires.

    Samples inside a gap are fabricated by the interpolation; the caller
    shades those intervals so they are not mistaken for real data.
    """
    uniform = np.arange(0.0, elapsed[-1], 1.0 / fs)
    axes = {name: np.interp(uniform, elapsed, frame[name].to_numpy(float))
            for name in 'xyz'}
    return uniform, axes


def vibration_signal(axes, axis, fs):
    """Build the signal to transform, with gravity and drift removed."""
    if axis == 'magnitude':
        # the norm is orientation independent; since |a| is dominated by
        # gravity, subtracting its mean leaves the vibration along g
        signal = np.sqrt(axes['x'] ** 2 + axes['y'] ** 2 + axes['z'] ** 2)
    else:
        signal = axes[axis]
    sos = sg.butter(4, HIGHPASS_CUTOFF, btype='highpass', fs=fs, output='sos')
    return sg.sosfiltfilt(sos, signal - signal.mean())


def spectrogram_db(signal, fs, seg_len, hop):
    """Return the power spectral density of the signal in dB.

    'psd' scaling is used rather than 'magnitude' so that the level of the
    broadband vibration does not shift when the window length is changed.
    A periodic (sym=False) window is the correct choice for spectral analysis.
    """
    window = sg.windows.hann(seg_len, sym=False)
    stft = sg.ShortTimeFFT(window, hop=hop, fs=fs,
                           fft_mode='onesided2X', scale_to='psd')
    psd = stft.spectrogram(signal)
    # stft.t() accounts for the padded slices at both ends, which start
    # before t = 0; those first and last few columns are not trustworthy
    return stft.t(signal.size), stft.f, 10 * np.log10(psd + 1e-12)


def plot(args, elapsed, gaps, states, t, f, psd_db):
    peak = psd_db.max()
    fig, ax = plt.subplots(figsize=(10, 5))
    mesh = ax.pcolormesh(t, f, psd_db, cmap=args.cmap, shading='nearest',
                         vmin=peak - args.dynamic_range, vmax=peak)
    fig.colorbar(mesh, ax=ax, label=r'PSD [dB re 1 (m/s$^2$)$^2$/Hz]')

    # button presses are the ground truth labels for the vibration analysis
    for i in np.flatnonzero(np.diff(states)) + 1:
        ax.axvline(elapsed[i], color='w', linestyle='--', linewidth=1.0)
        ax.text(elapsed[i], f[-1], STATE_NAMES.get(states[i], '?'),
                color='w', fontsize=8, ha='left', va='top')
    for i in gaps:
        # interpolated, not measured; hatched so it stands out on any colormap
        ax.axvspan(elapsed[i], elapsed[i + 1], facecolor='none',
                   edgecolor='r', hatch='//', linewidth=0.0)

    ax.set_xlabel('t [s]')
    ax.set_ylabel('f [Hz]')
    ax.set_ylim(0, args.fs / 2)
    ax.set_title('{}  ({})'.format(os.path.basename(args.csv), args.axis))
    fig.tight_layout()
    if args.output:
        fig.savefig(args.output, dpi=150)
        print('wrote {}'.format(args.output))
    else:
        plt.show()


def main():
    args = parse_args()
    frame = pd.read_csv(args.csv)

    elapsed, deltas = elapsed_seconds(frame['ticks_ms'].to_numpy(np.int64))
    gaps = report_sampling(elapsed, deltas)

    _, axes = resample(elapsed, frame, args.fs)
    signal = vibration_signal(axes, args.axis, args.fs)
    t, f, psd_db = spectrogram_db(signal, args.fs, args.seg_len, args.hop)
    print('resolution:    {:.2f} s x {:.3f} Hz'.format(
        args.hop / args.fs, args.fs / args.seg_len))

    plot(args, elapsed, gaps, frame['state'].to_numpy(), t, f, psd_db)


if __name__ == '__main__':
    main()
