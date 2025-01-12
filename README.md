# KubeKeeper - Docker Container Monitoring Tool

**Description:**

KubeKeeper is a simple yet effective command-line tool for monitoring your Docker containers. It provides real-time insights into CPU, memory, and I/O usage of your containers. Furthermore, it attempts to automatically diagnose and fix containers that are detected as unhealthy, increasing the resilience of your Docker environment.

**Features:**

*   **Real-time Monitoring:** Displays live CPU, memory, and I/O usage for all running Docker containers.
*   **Threshold-based Alerts:**  Alerts you when a container exceeds specified CPU or memory usage thresholds.
*   **Auto-Healing:** Detects unhealthy containers (based on Docker's health checks) and attempts to fix them by restarting or recreating them.
*   **Verbose Output:** Provides detailed information about the monitoring and auto-healing processes.
*   **Cross-Platform:** Works on any system where Docker and the Python Docker SDK are installed.

**Getting Started:**

**Prerequisites:**

*   **Python 3.6+:**  Make sure you have Python installed.
*   **Docker:** Docker needs to be installed and running.
*   **Docker SDK for Python:** Install the required library using pip:
    ```bash
    pip install docker
    ```

**Installation:**

1. Clone this repository:
    ```bash
    git clone [repository-url]
    cd kube-keeper
    ```
2. Alternatively, you can just download the `kubekeeper.py` file.

**Usage:**

Run the script from your terminal:

```bash
python kubekeeper.py
```
Optional Arguments:

--cpu-threshold <value>: Set the CPU usage threshold (in percentage) for alerts. Default is 80.
```bash
python kubekeeper.py --cpu-threshold 70
```
--mem-threshold <value>: Set the memory usage threshold (in percentage) for alerts. Default is 80.
```bash
python kubekeeper.py --mem-threshold 90
```

-h or --help: Display the help message with available options.
```bash
python kubekeeper.py -h
```

Example Output:
```bash
Starting KubeKeeper - Your Minimalist Docker Containers Monitor

Actively monitoring Docker containers... Press Ctrl+C to stop.

---------------------------------------------------------------------------
Container                  CPU Usage  Memory Usage              I/O Usage
---------------------------------------------------------------------------
my-web-app               15.32%     512.50 MB / 2.00 GB       25.67 MB
database                   2.10%      300.10 MB / 4.00 GB       10.20 MB
redis                    0.50%      50.00 MB / 1.00 GB        1.00 MB
---------------------------------------------------------------------------
```
Auto-Healing in Action:

When an unhealthy container is detected, you will see output similar to this:
```bash
Unhealthy container detected: my-misbehaving-app (Health Status: unhealthy). Initiating diagnosis...

🩺 Diagnosing container: my-misbehaving-app
🚦 Container my-misbehaving-app is not running (Status: exited). Attempting to restart...
✅ Successfully restarted my-misbehaving-app.
```
Or, if recreation is necessary:
```bash
Unhealthy container detected: another-problematic-container (Health Status: unhealthy). Initiating diagnosis...

🩺 Diagnosing container: another-problematic-container
📜 Last 10 log lines from another-problematic-container:
... (container logs) ...
🛠️ Container another-problematic-container is still problematic. Attempting to recreate...
Stopping the problematic container: another-problematic-container
Removing the problematic container: another-problematic-container
Recreating container another-problematic-container from image: my-image:latest
✅ Successfully recreated another-problematic-container from my-image:latest.
Use code with caution.
```
If auto-healing fails:
```bash
Unhealthy container detected: persistent-issue (Health Status: unhealthy). Initiating diagnosis...

🩺 Diagnosing container: persistent-issue
... (diagnosis steps) ...
🛑 Failed to fix persistent-issue. Stopping monitoring and attempting to stop the container.
Successfully stopped container: persistent-issue
Use code with caution.
```
**Contributing**:

Feel free to fork this repository and submit pull requests for improvements or bug fixes.

 **License**:

This project is licensed under the Choose a License, MIT License.

 **Potential Improvements (Future Enhancements)**:

More sophisticated health check analysis.

Configuration file for thresholds and other settings.

Integration with notification services (e.g., Slack, email).

Support for Docker Compose.

Web-based interface for visualization.
