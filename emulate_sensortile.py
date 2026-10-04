import time
import random
import numpy as np

print("=== STMicroelectronics SensorTile.box (Emulated) ===")
print("Hardware: LSM6DSOX 6-axis IMU [Emulated Mode]")
print("Model: NanoEdge AI Anomaly Detection Engine")
print("Status: Streaming Accelerometer Telemetry...\n")

def generate_accelerometer_data():
    # Normal walking baseline: ~1.0g on Z-axis due to gravity, small noise on X/Y
    ax = random.uniform(-0.1, 0.1)
    ay = random.uniform(-0.1, 0.1)
    az = random.uniform(0.9, 1.1)
    
    # 10% chance to simulate a sudden motion anomaly / fall event
    if random.random() < 0.10:
        ax = random.uniform(2.5, 4.0)  # Spike in horizontal force
        ay = random.uniform(2.0, 3.5)
        az = random.uniform(0.1, 0.4)  # Free-fall / impact drop
        
    return ax, ay, az

def anomaly_detection_model(ax, ay, az):
    # Calculate resultant acceleration vector magnitude
    magnitude = np.sqrt(ax**2 + ay**2 + az**2)
    # Threshold for abnormal motion / fall event (> 2.5g)
    if magnitude > 2.5:
        return True, magnitude
    return False, magnitude

while True:
    ax, ay, az = generate_accelerometer_data()
    is_anomaly, mag = anomaly_detection_model(ax, ay, az)
    
    timestamp = time.strftime("%H:%M:%S")
    if is_anomaly:
        print(f"[{timestamp}] [ANOMALY DETECTED] Mag: {mag:.2f}g | Accel (X:{ax:.2f}, Y:{ay:.2f}, Z:{az:.2f}) -> TRIGGERING ALERT")
    else:
        print(f"[{timestamp}] [Normal Motion]    Mag: {mag:.2f}g | Accel (X:{ax:.2f}, Y:{ay:.2f}, Z:{az:.2f})")
        
    time.sleep(1)
