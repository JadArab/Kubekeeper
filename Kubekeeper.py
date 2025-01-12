import docker
import time
import argparse
import os

def format_size(bytes_value):
    """Convert bytes to human-readable format."""

    if bytes_value == "N/A":
        return "N/A"
    try:
        bytes_value = int(bytes_value)
    except (ValueError, TypeError):
        return "N/A"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_value < 1024:
            return f"{bytes_value:.2f} {unit}"
        bytes_value /= 1024
    return f"{bytes_value:.2f} TB"

def get_container_stats(container):
    """Fetches container stats, handling errors."""
    try:
        stats = container.stats(stream=False)
        cpu_stats = stats.get("cpu_stats", {})
        precpu_stats = stats.get("precpu_stats", {})

        cpu_delta = cpu_stats.get("cpu_usage", {}).get("total_usage", 0) - precpu_stats.get("cpu_usage", {}).get("total_usage", 0)
        system_delta = cpu_stats.get("system_cpu_usage", 0) - precpu_stats.get("system_cpu_usage", 0)

        cpu_usage = (cpu_delta / system_delta * 100) if system_delta > 0 else 0
        cpu_usage_percent = float(f"{cpu_usage:.2f}")

        memory_stats = stats.get("memory_stats", {})
        used_memory = memory_stats.get("usage", 0)
        total_memory = memory_stats.get("limit", 1)
        memory_percent = (used_memory / total_memory) * 100

        blkio_stats = stats.get("blkio_stats", {}).get("io_service_bytes_recursive", [])
        io_usage = sum(entry["value"] for entry in blkio_stats if "value" in entry) if blkio_stats else 0

        return {
            "cpu_percent": cpu_usage_percent,
            "cpu_usage": f"{cpu_usage:.2f}%",
            "memory_percent": memory_percent,
            "memory_usage": f"{format_size(used_memory)} / {format_size(total_memory)}",
            "io_usage": format_size(io_usage),
        }
    except docker.errors.APIError as e:
        print(f"Docker API error fetching stats for {container.name}: {e}")
        return {}
    except Exception as e:
        print(f"Unexpected error fetching stats for {container.name}: {e}")
        return {}

def diagnose_and_fix(container, client):
    """Attempts to diagnose and fix an unhealthy container."""
    print(f"\n🩺 Diagnosing container: {container.name}")
    try:
        container.reload()  # Refresh container state
        if container.status != "running":
            print(f"🚦 Container {container.name} is not running (Status: {container.status}). Attempting to restart...")
            try:
                container.restart()
                time.sleep(5)
                container.reload()
                if container.status == "running":
                    print(f"Successfully restarted {container.name}.")
                    return True
                else:
                    print(f"Failed to restart {container.name}. Status remains: {container.status}")
                    return False
            except docker.errors.APIError as e:
                print(f"Docker API error during restart of {container.name}: {e}")
                return False
            except Exception as e:
                print(f"Unexpected error during restart of {container.name}: {e}")
                return False

        logs = container.logs(tail=10).decode("utf-8", errors="ignore")
        print(f"📜 Last 10 log lines from {container.name}:\n{logs}")

        print(f"🛠️ Container {container.name} is still problematic. Attempting to recreate...")
        try:
            image = container.image.tags[0] if container.image.tags else container.image.id
            container_name = container.name
            config = container.attrs['Config']
            host_config = container.attrs['HostConfig']
            networking_config = container.attrs['NetworkSettings']

            print(f"Stopping the problematic container: {container_name}")
            container.stop()
            print(f"Removing the problematic container: {container_name}")
            container.remove()

            print(f"Recreating container {container_name} from image: {image}")
            new_container = client.containers.run(
                image,
                detach=True,
                name=container_name,
                ports=config.get('ExposedPorts'),
                environment=config.get('Env'),
                volumes=host_config.get('Binds'),
                network_mode=host_config.get('NetworkMode'),
                restart_policy=host_config.get('RestartPolicy'),
                labels=config.get('Labels')
                # Add other configurations as needed
            )
            print(f"Successfully recreated {new_container.name} from {image}.")
            return True

        except docker.errors.APIError as e:
            print(f"Docker API error during recreation of {container.name}: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error during recreation of {container.name}: {e}")
            return False

    except docker.errors.APIError as e:
        print(f"Docker API error while diagnosing {container.name}: {e}")
        return False
    except Exception as e:
        print(f"Critical failure: Unable to diagnose {container.name}. Error: {e}")
        return False

def print_table(data):
    """Prints formatted container stats."""
    if not data:
        return
    print("-" * 75)
    print(f"{'Container':<25} {'CPU Usage':<10} {'Memory Usage':<25} {'I/O Usage':<10}")
    print("-" * 75)
    for row in data:
        print(f"{row['Container']:<25} {row['cpu_usage']:<10} {row['memory_usage']:<25} {row['io_usage']:<10}")
    print("-" * 75)

def monitor_containers(cpu_threshold, mem_threshold):
    """Monitors containers and alerts on thresholds."""
    print("\nStarting KubeKeeper - Your Minimalist Docker Containers Monitor \n")
    try:
        client = docker.from_env()
    except docker.errors.DockerException as e:
        print(f"Docker connection error: {e}. Please ensure Docker is running and accessible.")
        return

    print("Actively monitoring Docker containers... Press Ctrl+C to stop.\n")
    monitored_containers = {}

    while True:
        try:
            containers = client.containers.list()
            current_container_names = {c.name for c in containers}

            # Remove stopped containers from monitoring
            for name in list(monitored_containers.keys()):
                if name not in current_container_names:
                    del monitored_containers[name]
                    print(f"Container {name} has stopped. Removed from monitoring.")

            table_data = []
            for container in containers:
                if container.name not in monitored_containers:
                    monitored_containers[container.name] = True
                    print(f"Started monitoring new container: {container.name}")

                stats = get_container_stats(container)
                if not stats:
                    continue

                table_data.append({
                    "Container": container.name,
                    "cpu_usage": stats.get("cpu_usage", "N/A"),
                    "memory_usage": stats.get("memory_usage", "N/A"),
                    "io_usage": stats.get("io_usage", "N/A"),
                })

                # Check container health status
                try:
                    container.reload()
                    if hasattr(container, "attrs") and "State" in container.attrs and "Health" in container.attrs["State"]:
                        health_status = container.attrs["State"]["Health"]["Status"]
                        if health_status != "healthy":
                            print(f"Unhealthy container detected: {container.name} (Health Status: {health_status}). Initiating diagnosis...")
                            if not diagnose_and_fix(container, client):
                                print(f"Failed to fix {container.name}. Stopping monitoring and attempting to stop the container.")
                                del monitored_containers[container.name]
                                try:
                                    container.stop()
                                    print(f"Successfully stopped container: {container.name}")
                                except docker.errors.APIError as e:
                                    print(f"Error stopping container {container.name}: {e}")
                                except Exception as e:
                                    print(f"Unexpected error while stopping container {container.name}: {e}")
                            continue  # Skip resource checks if container was unhealthy and handled
                except docker.errors.APIError as e:
                    print(f"Docker API error checking health of {container.name}: {e}")
                except Exception as e:
                    print(f"Error checking health of {container.name}: {e}")

                # Only check resource usage if the container is considered healthy by Docker
                if stats.get("cpu_percent", 0) > cpu_threshold:
                    print(f"CPU ALERT: {container.name} - {stats['cpu_usage']} (Threshold: {cpu_threshold}%)")

                if stats.get("memory_percent", 0) > mem_threshold:
                    print(f"MEMORY ALERT: {container.name} - {stats['memory_usage']} (Threshold: {mem_threshold}%)")

            os.system('cls' if os.name == 'nt' else 'clear')
            print_table(table_data)
            time.sleep(5)

        except KeyboardInterrupt:
            print("\nMonitoring stopped by user.")
            break
        except docker.errors.APIError as e:
            print(f"Docker API Error: {e}. Retrying in 5 seconds...")
            time.sleep(5)
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            break

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="""
KubeKeeper - Your friendly Docker container monitoring tool.

Monitors Docker containers, displays resource usage, and attempts to diagnose and fix unhealthy containers.
""",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--cpu-threshold", type=float, default=80, help="CPU usage threshold (percentage).")
    parser.add_argument("--mem-threshold", type=float, default=80, help="Memory usage threshold (percentage).")

    args = parser.parse_args()

    monitor_containers(args.cpu_threshold, args.mem_threshold)





