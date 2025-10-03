#!/usr/bin/env python3
"""
Jupyter Notebook Live Execution Logger
Starts a Jupyter notebook server and captures all cell executions in real-time.
"""

import sys
import json
import argparse
import threading
import time
from datetime import datetime
from pathlib import Path
import subprocess
import jupyter_client
from jupyter_client import KernelManager
import queue
import signal


class NotebookExecutionLogger:
    """Monitors and logs Jupyter notebook kernel executions."""
    
    def __init__(self, log_file):
        self.log_file = log_file
        self.cell_count = 0
        self.running = True
        
        # Initialize log file
        with open(log_file, 'w') as f:
            f.write(f"Jupyter Notebook Execution Log\n")
            f.write(f"Started at: {datetime.now().isoformat()}\n")
            f.write('=' * 80 + '\n\n')
    
    def log_entry(self, entry):
        """Write a log entry to the file."""
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(entry, indent=2) + '\n')
            f.write('-' * 80 + '\n')
    
    def monitor_kernel(self, kernel_id, connection_file):
        """Monitor a specific kernel and log its executions."""
        try:
            # Connect to the existing kernel
            km = KernelManager(connection_file=connection_file)
            km.load_connection_file()
            kc = km.client()
            kc.start_channels()
            
            print(f"Monitoring kernel: {kernel_id}")
            
            while self.running:
                try:
                    # Check for messages on different channels
                    if kc.iopub_channel.msg_ready():
                        msg = kc.get_iopub_msg(timeout=0.1)
                        self.process_message(msg, kernel_id)
                    
                    if kc.shell_channel.msg_ready():
                        msg = kc.get_shell_msg(timeout=0.1)
                        self.process_shell_message(msg, kernel_id)
                    
                    if kc.stdin_channel.msg_ready():
                        msg = kc.get_stdin_msg(timeout=0.1)
                        self.process_stdin_message(msg, kernel_id)
                    
                    time.sleep(0.01)  # Small delay to prevent CPU spinning
                    
                except queue.Empty:
                    continue
                except Exception as e:
                    print(f"Error monitoring kernel: {e}")
                    time.sleep(1)
            
            kc.stop_channels()
            
        except Exception as e:
            print(f"Failed to monitor kernel {kernel_id}: {e}")
    
    def process_message(self, msg, kernel_id):
        """Process IOPub messages (outputs)."""
        msg_type = msg['header']['msg_type']
        content = msg['content']
        
        if msg_type == 'execute_input':
            self.cell_count += 1
            log_entry = {
                'timestamp': datetime.now().isoformat(),
                'kernel_id': kernel_id,
                'cell_number': self.cell_count,
                'type': 'input',
                'execution_count': content.get('execution_count'),
                'code': content.get('code', '')
            }
            self.log_entry(log_entry)
            print(f"[Cell {self.cell_count}] Execution started")
        
        elif msg_type == 'stream':
            log_entry = {
                'timestamp': datetime.now().isoformat(),
                'kernel_id': kernel_id,
                'type': 'stream',
                'stream_name': content.get('name'),  # stdout or stderr
                'content': content.get('text', '')
            }
            self.log_entry(log_entry)
            stream_type = content.get('name', 'output')
            print(f"[{stream_type.upper()}] {content.get('text', '').strip()}")
        
        elif msg_type == 'execute_result':
            log_entry = {
                'timestamp': datetime.now().isoformat(),
                'kernel_id': kernel_id,
                'type': 'output',
                'execution_count': content.get('execution_count'),
                'data': content.get('data', {})
            }
            self.log_entry(log_entry)
            print(f"[OUTPUT] {content.get('data', {}).get('text/plain', '')}")
        
        elif msg_type == 'error':
            log_entry = {
                'timestamp': datetime.now().isoformat(),
                'kernel_id': kernel_id,
                'type': 'error',
                'error_name': content.get('ename'),
                'error_value': content.get('evalue'),
                'traceback': content.get('traceback', [])
            }
            self.log_entry(log_entry)
            print(f"[ERROR] {content.get('ename')}: {content.get('evalue')}")
        
        elif msg_type == 'display_data':
            log_entry = {
                'timestamp': datetime.now().isoformat(),
                'kernel_id': kernel_id,
                'type': 'display',
                'data': content.get('data', {})
            }
            self.log_entry(log_entry)
    
    def process_shell_message(self, msg, kernel_id):
        """Process shell messages (execution requests/replies)."""
        msg_type = msg['header']['msg_type']
        
        if msg_type == 'execute_reply':
            content = msg['content']
            log_entry = {
                'timestamp': datetime.now().isoformat(),
                'kernel_id': kernel_id,
                'type': 'execute_reply',
                'status': content.get('status'),
                'execution_count': content.get('execution_count')
            }
            self.log_entry(log_entry)
    
    def process_stdin_message(self, msg, kernel_id):
        """Process stdin messages (input requests)."""
        content = msg['content']
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'kernel_id': kernel_id,
            'type': 'stdin',
            'prompt': content.get('prompt', ''),
            'password': content.get('password', False)
        }
        self.log_entry(log_entry)
        print(f"[STDIN] Input requested: {content.get('prompt', '')}")


def find_running_kernels():
    """Find all running Jupyter kernels."""
    try:
        from jupyter_client import find_connection_file
        from jupyter_client.kernelspec import KernelSpecManager
        import jupyter_core.paths
        
        runtime_dir = jupyter_core.paths.jupyter_runtime_dir()
        kernel_files = list(Path(runtime_dir).glob('kernel-*.json'))
        
        kernels = []
        for kf in kernel_files:
            kernel_id = kf.stem.replace('kernel-', '')
            kernels.append({
                'id': kernel_id,
                'connection_file': str(kf)
            })
        
        return kernels
    except Exception as e:
        print(f"Error finding kernels: {e}")
        return []


def monitor_all_kernels(logger):
    """Monitor all running kernels continuously."""
    monitored_kernels = set()
    threads = []
    
    print("Starting kernel monitor (checking for new kernels every 2 seconds)...")
    print("Press Ctrl+C to stop\n")
    
    try:
        while logger.running:
            kernels = find_running_kernels()
            
            for kernel in kernels:
                kernel_id = kernel['id']
                if kernel_id not in monitored_kernels:
                    monitored_kernels.add(kernel_id)
                    thread = threading.Thread(
                        target=logger.monitor_kernel,
                        args=(kernel_id, kernel['connection_file']),
                        daemon=True
                    )
                    thread.start()
                    threads.append(thread)
            
            time.sleep(2)
    
    except KeyboardInterrupt:
        print("\n\nStopping kernel monitoring...")
        logger.running = False


def start_jupyter_notebook(notebook_dir=None, port=8888):
    """Start Jupyter notebook server."""
    cmd = ['jupyter', 'notebook']
    
    if notebook_dir:
        cmd.extend(['--notebook-dir', notebook_dir])
    
    cmd.extend([
        '--port', str(port),
        '--no-browser'
    ])
    
    print(f"Starting Jupyter notebook server on port {port}...")
    print(f"Command: {' '.join(cmd)}\n")
    
    return subprocess.Popen(cmd)


def main():
    parser = argparse.ArgumentParser(
        description='Start Jupyter notebook and log all cell executions in real-time'
    )
    parser.add_argument(
        '-o', '--output',
        default='jupyter_live_execution.log',
        help='Output log file (default: jupyter_live_execution.log)'
    )
    parser.add_argument(
        '-d', '--notebook-dir',
        default='.',
        help='Notebook directory (default: current directory)'
    )
    parser.add_argument(
        '-p', '--port',
        type=int,
        default=8888,
        help='Jupyter server port (default: 8888)'
    )
    parser.add_argument(
        '--no-start',
        action='store_true',
        help='Do not start Jupyter server, only monitor existing kernels'
    )
    
    args = parser.parse_args()
    
    # Create logger
    logger = NotebookExecutionLogger(args.output)
    print(f"Logging to: {args.output}\n")
    
    # Start Jupyter server if requested
    jupyter_process = None
    if not args.no_start:
        jupyter_process = start_jupyter_notebook(args.notebook_dir, args.port)
        time.sleep(3)  # Give server time to start
    
    # Setup signal handler for clean shutdown
    def signal_handler(sig, frame):
        print("\n\nShutting down...")
        logger.running = False
        if jupyter_process:
            print("Stopping Jupyter server...")
            jupyter_process.terminate()
            jupyter_process.wait()
        
        # Write completion message
        with open(args.output, 'a') as f:
            f.write('\n' + '=' * 80 + '\n')
            f.write(f"Stopped at: {datetime.now().isoformat()}\n")
            f.write(f"Total cells executed: {logger.cell_count}\n")
        
        print(f"\nLog saved to: {args.output}")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    # Monitor kernels
    try:
        monitor_all_kernels(logger)
    except Exception as e:
        print(f"Error: {e}")
        if jupyter_process:
            jupyter_process.terminate()
        sys.exit(1)


if __name__ == '__main__':
    main()