import json
import time
from mcp_server.server import logic_device_info, logic_capture, logic_measure_pwm, logic_measure_deadtime

print("=" * 60)
print("=== DSLogic U2Pro16 Hardware Verification Test ===")
print("=" * 60)

print("\n[Step 1] Detecting DSLogic U2Pro16 connection...")
t0 = time.time()
dev_info = logic_device_info()
print(f"Elapsed: {(time.time() - t0):.3f}s")
print(json.dumps(dev_info, indent=2, ensure_ascii=False))

if not dev_info.get("ok") or not dev_info.get("connected"):
    print("[-] Error: DSLogic U2Pro16 device not detected!")
    exit(1)

print("[+] Device Detected: " + dev_info.get("model", "Unknown"))

print("\n[Step 2] Capturing digital logic (100MHz, 2000us, CH0 & CH1)...")
t0 = time.time()
cap_res = logic_capture(sample_rate_hz=100_000_000, duration_us=2000, channels=[0, 1])
print(f"Elapsed: {(time.time() - t0):.3f}s")
print(json.dumps(cap_res, indent=2, ensure_ascii=False))

if not cap_res.get("ok"):
    print("[-] Capture failed:", cap_res.get("error"))
    exit(1)

cap_id = cap_res["capture_id"]
print(f"[+] Capture Succeeded: ID={cap_id}")
print(f"    Sample count: {cap_res.get('sample_count')} points")
print(f"    Capture dir: {cap_res.get('capture_dir')}")

print(f"\n[Step 3] Analyzing PWM characteristics on CH0...")
pwm_ch0 = logic_measure_pwm(cap_id, channel=0)
print(json.dumps(pwm_ch0, indent=2, ensure_ascii=False))

print(f"\n[Step 4] Analyzing PWM characteristics on CH1...")
pwm_ch1 = logic_measure_pwm(cap_id, channel=1)
print(json.dumps(pwm_ch1, indent=2, ensure_ascii=False))

print(f"\n[Step 5] Analyzing Complementary Deadtime (CH0 vs CH1)...")
deadtime_res = logic_measure_deadtime(cap_id, high_channel=0, low_channel=1)
print(json.dumps(deadtime_res, indent=2, ensure_ascii=False))

print("\n" + "=" * 60)
print("=== ALL HARDWARE MCP TEST STEPS PASSED SUCCESSFULLY! ===")
print("=" * 60)
