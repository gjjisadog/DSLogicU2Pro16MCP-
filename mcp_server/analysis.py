import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

def load_capture(capture_id_or_dir: str, base_dir: str = "captures") -> Tuple[np.ndarray, Dict[str, Any], Path]:
    p = Path(capture_id_or_dir)
    if not p.is_dir():
        p = Path(base_dir) / capture_id_or_dir
    if not p.exists():
        raise FileNotFoundError(f"Capture directory not found: {p}")
    json_path = p / "capture.json"
    bin_path = p / "capture.bin"
    if not json_path.exists():
        raise FileNotFoundError(f"Metadata file missing: {json_path}")
    if not bin_path.exists():
        raise FileNotFoundError(f"Raw data file missing: {bin_path}")
    with open(json_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    samples = np.fromfile(bin_path, dtype="<u2")
    return samples, meta, p

def measure_pwm(capture_id_or_dir: str, channel: int = 0, base_dir: str = "captures") -> Dict[str, Any]:
    if channel < 0 or channel > 15:
        raise ValueError(f"Channel must be between 0 and 15, got {channel}")
    samples, meta, cap_dir = load_capture(capture_id_or_dir, base_dir)
    sample_rate_hz = meta.get("sample_rate_hz", 100_000_000)
    bit_signal = ((samples >> channel) & 1).astype(np.int8)
    num_ones = int(np.count_nonzero(bit_signal))
    if num_ones == 0:
        return {
            "ok": False,
            "error": f"Channel {channel} is constant LOW (0V). No transitions detected.",
            "channel": channel,
            "sample_rate_hz": sample_rate_hz,
            "total_samples": len(samples),
        }
    if num_ones == len(bit_signal):
        return {
            "ok": False,
            "error": f"Channel {channel} is constant HIGH (3.3V/Vcc). No transitions detected.",
            "channel": channel,
            "sample_rate_hz": sample_rate_hz,
            "total_samples": len(samples),
        }
    diff = np.diff(bit_signal)
    rising_indices = np.where(diff == 1)[0] + 1
    falling_indices = np.where(diff == -1)[0] + 1
    if len(rising_indices) < 2 or len(falling_indices) < 1:
        return {
            "ok": False,
            "error": f"Insufficient edges detected on channel {channel} (rising: {len(rising_indices)}, falling: {len(falling_indices)}).",
            "channel": channel,
            "sample_rate_hz": sample_rate_hz,
            "total_samples": len(samples),
            "rising_edge_count": int(len(rising_indices)),
            "falling_edge_count": int(len(falling_indices)),
        }
    periods_s = []
    high_times_s = []
    low_times_s = []
    duty_cycles_pct = []
    f_idx = 0
    num_falling = len(falling_indices)
    for i in range(len(rising_indices) - 1):
        r_start = rising_indices[i]
        r_next = rising_indices[i + 1]
        while f_idx < num_falling and falling_indices[f_idx] <= r_start:
            f_idx += 1
        if f_idx < num_falling and falling_indices[f_idx] < r_next:
            f_edge = falling_indices[f_idx]
            period_samples = r_next - r_start
            high_samples = f_edge - r_start
            low_samples = r_next - f_edge
            period_sec = period_samples / sample_rate_hz
            high_sec = high_samples / sample_rate_hz
            low_sec = low_samples / sample_rate_hz
            duty_pct = (high_samples / period_samples) * 100.0
            periods_s.append(period_sec)
            high_times_s.append(high_sec)
            low_times_s.append(low_sec)
            duty_cycles_pct.append(duty_pct)
    if not periods_s:
        return {
            "ok": False,
            "error": f"Could not construct complete PWM cycles on channel {channel}.",
            "channel": channel,
        }
    periods_arr = np.array(periods_s)
    high_arr = np.array(high_times_s)
    low_arr = np.array(low_times_s)
    duty_arr = np.array(duty_cycles_pct)
    mean_period = float(np.mean(periods_arr))
    mean_freq = float(1.0 / mean_period) if mean_period > 0 else 0.0
    return {
        "ok": True,
        "channel": channel,
        "capture_id": meta.get("capture_id", Path(cap_dir).name),
        "sample_rate_hz": sample_rate_hz,
        "cycle_count": int(len(periods_arr)),
        "frequency_hz": round(mean_freq, 3),
        "period_s": float(mean_period),
        "period_us": round(float(mean_period * 1e6), 4),
        "min_period_us": round(float(np.min(periods_arr) * 1e6), 4),
        "max_period_us": round(float(np.max(periods_arr) * 1e6), 4),
        "duty_cycle_percent": round(float(np.mean(duty_arr)), 3),
        "min_duty_cycle_percent": round(float(np.min(duty_arr)), 3),
        "max_duty_cycle_percent": round(float(np.max(duty_arr)), 3),
        "high_time_us": round(float(np.mean(high_arr) * 1e6), 4),
        "low_time_us": round(float(np.mean(low_arr) * 1e6), 4),
    }

def measure_deadtime(capture_id_or_dir: str, high_ch: int = 0, low_ch: int = 1, base_dir: str = "captures") -> Dict[str, Any]:
    if high_ch == low_ch:
        raise ValueError("high_ch and low_ch must be different channels")
    if high_ch < 0 or high_ch > 15 or low_ch < 0 or low_ch > 15:
        raise ValueError("Channels must be between 0 and 15")
    samples, meta, cap_dir = load_capture(capture_id_or_dir, base_dir)
    sample_rate_hz = meta.get("sample_rate_hz", 100_000_000)
    hs = ((samples >> high_ch) & 1).astype(np.int8)
    ls = ((samples >> low_ch) & 1).astype(np.int8)
    shoot_through_mask = (hs == 1) & (ls == 1)
    shoot_through_count = int(np.count_nonzero(shoot_through_mask))
    has_shoot_through = (shoot_through_count > 0)
    shoot_through_duration_ns = (shoot_through_count / sample_rate_hz) * 1e9
    diff_hs = np.diff(hs)
    diff_ls = np.diff(ls)
    hs_rising = np.where(diff_hs == 1)[0] + 1
    hs_falling = np.where(diff_hs == -1)[0] + 1
    ls_rising = np.where(diff_ls == 1)[0] + 1
    ls_falling = np.where(diff_ls == -1)[0] + 1
    dt_hs_fall_to_ls_rise_ns = []
    ls_r_idx = 0
    num_ls_r = len(ls_rising)
    for h_fall in hs_falling:
        while ls_r_idx < num_ls_r and ls_rising[ls_r_idx] < h_fall:
            ls_r_idx += 1
        if ls_r_idx < num_ls_r:
            l_rise = ls_rising[ls_r_idx]
            diff_samples = l_rise - h_fall
            dt_ns = (diff_samples / sample_rate_hz) * 1e9
            dt_hs_fall_to_ls_rise_ns.append(dt_ns)
    dt_ls_fall_to_hs_rise_ns = []
    hs_r_idx = 0
    num_hs_r = len(hs_rising)
    for l_fall in ls_falling:
        while hs_r_idx < num_hs_r and hs_rising[hs_r_idx] < l_fall:
            hs_r_idx += 1
        if hs_r_idx < num_hs_r:
            h_rise = hs_rising[hs_r_idx]
            diff_samples = h_rise - l_fall
            dt_ns = (diff_samples / sample_rate_hz) * 1e9
            dt_ls_fall_to_hs_rise_ns.append(dt_ns)
    def stats_dict(arr):
        if not arr:
            return {"count": 0, "mean_ns": None, "min_ns": None, "max_ns": None}
        np_arr = np.array(arr)
        return {
            "count": int(len(np_arr)),
            "mean_ns": round(float(np.mean(np_arr)), 2),
            "min_ns": round(float(np.min(np_arr)), 2),
            "max_ns": round(float(np.max(np_arr)), 2),
        }
    return {
        "ok": True,
        "high_channel": high_ch,
        "low_channel": low_ch,
        "capture_id": meta.get("capture_id", Path(cap_dir).name),
        "sample_rate_hz": sample_rate_hz,
        "has_shoot_through": has_shoot_through,
        "shoot_through_samples": shoot_through_count,
        "shoot_through_duration_ns": round(shoot_through_duration_ns, 2),
        "hs_fall_to_ls_rise": stats_dict(dt_hs_fall_to_ls_rise_ns),
        "ls_fall_to_hs_rise": stats_dict(dt_ls_fall_to_hs_rise_ns),
    }
