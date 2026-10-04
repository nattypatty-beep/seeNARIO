import time
import math
import subprocess

# STMicroelectronics SensorTile.box IMU Configuration (LSM6DSOX 3-axis Accelerometer)
SAMPLE_RATE_HZ = 104
ANOMALY_THRESHOLD_G = 2.5  # Threshold for abnormal motion / stumble / fall

def read_sensortile_accel():
    """
    Simulates or reads raw 3-axis acceleration (ax, ay, az) in g-forces
    from the ST SensorTile.box over Bluetooth Low Energy (BLE) or Serial interface.
    """
    # Replace with real BLE/Serial read loop from ST SensorTile stream
    import random
    ax = random.uniform(-0.2, 0.2)
    ay = random.uniform(-0.2, 0.2)
    az = random.uniform(0.9, 1.1)
    
    # Simulate an occasional motion anomaly event
    if random.random() < 0.05:
        ax, ay, az = random.uniform(2.0, 3.5), random.uniform(1.5, 3.0), random.uniform(0.1, 0.5)
        
    return ax, ay, az

def evaluate_anomaly_model(ax, ay, az):
    """
    Evaluates spatial motion vector magnitude to classify normal vs abnormal motion.
    (Emulates ST NanoEdge AI Studio Anomaly Detection inference output)
    """
    magnitude = math.sqrt(ax**2 + ay**2 + az**2)
    is_anomaly = magnitude > ANOMALY_THRESHOLD_G
    return is_anomaly, magnitude

def main():
    print("[SensorTile.box] Initializing LSM6DSOX Motion Sensor Stream...")
    print("[Edge-AI] Loading ST NanoEdge AI Anomaly Detection Engine...")
    
    while True:
        ax, ay, az = read_sensortile_accel()
        anomaly_detected, mag = evaluate_anomaly_model(ax, ay, az)
        
        if anomaly_detected:
            print(f"[ANOMALY DETECTED] Motion Vector: {mag:.2f}g -> Triggering Raspberry Pi Vision System...")
            # Execute main vision/audio binary on the Pi
            subprocess.run(["./main"])
            time.sleep(3.0)  # Debounce delay after trigger
            
        time.sleep(1.0 / SAMPLE_RATE_HZ)

if __name__ == "__main__":
    main()
