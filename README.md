
## Installation

```bash
pip install nbformat nbconvert jupyter jupyter-client
```

## Usage

```bash
# Start Jupyter and log executions (most common use case)
python script.py

# Specify custom log file
python script.py -o my_executions.log

# Start in specific directory
python script.py -d /path/to/notebooks

# Use custom port
python script.py -p 9999

# Only monitor existing Jupyter server (don't start new one)
python script.py --no-start
```

## How it works

- Starts a Jupyter notebook server (opens in your browser)
- Monitors for kernel activity in the background
- Captures every cell execution with timestamps
- Logs inputs, outputs, errors, and stdin requests
- Press Ctrl+C when done to stop gracefully

## What gets logged

- Cell input code with execution count
- stdout and stderr streams
- Execution results
- Error tracebacks
- Input prompts (when using input())
- Display data
- Execution status

The script will print activity to the console while also saving everything to the log file!

# Jupyter Notebook Execution Logger

A comprehensive tool for monitoring and logging Jupyter notebook executions in real-time. This tool captures all kernel activity including code execution, outputs, errors, and user interactions across multiple notebooks simultaneously.

## Overview

The script works by:
- Starting a Jupyter notebook server
- Discovering running Jupyter kernels
- Connecting to those kernels via their message channels
- Listening for messages on those channels in real-time
- Logging all captured messages to a file

## Key Components

### 1. NotebookExecutionLogger Class

This is the main logging engine that monitors kernel activity.

```python
class NotebookExecutionLogger:
    def __init__(self, log_file):
        self.log_file = log_file
        self.cell_count = 0
        self.running = True
```

**Properties:**
- `log_file`: Where to save execution logs
- `cell_count`: Tracks number of cells executed
- `running`: Flag to control the monitoring loop

### 2. Kernel Connection & Message Channels

This is the core mechanism for capturing stdin, stdout, and stderr:

```python
def monitor_kernel(self, kernel_id, connection_file):
    # Connect to existing kernel using its connection file
    km = KernelManager(connection_file=connection_file)
    km.load_connection_file()
    kc = km.client()
    kc.start_channels()
```

#### How Jupyter Kernels Work:
- Each notebook has a kernel (Python process) that executes code
- Kernels communicate via ZeroMQ message channels
- The connection file contains ports/keys to connect to these channels

#### Three Message Channels:

**IOPub Channel (kc.iopub_channel):** Broadcasts execution outputs
- `stdout` → stream messages with name='stdout'
- `stderr` → stream messages with name='stderr'
- Execution results
- Error tracebacks
- Display data

**Shell Channel (kc.shell_channel):** Request/reply for code execution
- Execution requests
- Execution status replies
- Metadata about execution

**Stdin Channel (kc.stdin_channel):** Input requests
- When code calls input(), kernel sends stdin request
- Captures prompts and whether it's a password field

### 3. The Monitoring Loop

```python
while self.running:
    # Check IOPub for outputs (stdout, stderr, results)
    if kc.iopub_channel.msg_ready():
        msg = kc.get_iopub_msg(timeout=0.1)
        self.process_message(msg, kernel_id)
    
    # Check Shell for execution status
    if kc.shell_channel.msg_ready():
        msg = kc.get_shell_msg(timeout=0.1)
        self.process_shell_message(msg, kernel_id)
    
    # Check Stdin for input requests
    if kc.stdin_channel.msg_ready():
        msg = kc.get_stdin_msg(timeout=0.1)
        self.process_stdin_message(msg, kernel_id)
```

**How it captures output:**
- Continuously polls each channel for new messages
- Non-blocking checks (`msg_ready()`) to avoid hanging
- `timeout=0.1` prevents blocking forever
- Small sleep prevents CPU spinning

## Message Processing Methods

### process_message() - Captures stdout, stderr, outputs

```python
def process_message(self, msg, kernel_id):
    msg_type = msg['header']['msg_type']
    content = msg['content']
```

**Message types and what they capture:**

#### 1. execute_input - Cell code (what you type):
```python
if msg_type == 'execute_input':
    log_entry = {
        'type': 'input',
        'code': content.get('code', '')  # The actual cell code
    }
```

#### 2. stream - This is where stdout/stderr are captured:
```python
elif msg_type == 'stream':
    log_entry = {
        'type': 'stream',
        'stream_name': content.get('name'),  # 'stdout' or 'stderr'
        'content': content.get('text', '')    # The actual output text
    }
```

**How it works:**
- When you run `print("hello")` → kernel sends stream message with name='stdout'
- When code raises warnings/errors → kernel sends stream message with name='stderr'
- The text field contains the actual output string

#### 3. execute_result - Return values:
```python
elif msg_type == 'execute_result':
    log_entry = {
        'data': content.get('data', {})  # Result data (text, HTML, images, etc.)
    }
```
Captures the last expression's value (e.g., `5 + 5` returns `10`)

#### 4. error - Exceptions and tracebacks:
```python
elif msg_type == 'error':
    log_entry = {
        'error_name': content.get('ename'),      # Exception name
        'error_value': content.get('evalue'),    # Error message
        'traceback': content.get('traceback')    # Full stack trace
    }
```

#### 5. display_data - Rich outputs (plots, images, HTML):
```python
elif msg_type == 'display_data':
    log_entry = {
        'data': content.get('data', {})  # Can be images, HTML, etc.
    }
```

### process_stdin_message() - Captures stdin/input requests

```python
def process_stdin_message(self, msg, kernel_id):
    content = msg['content']
    log_entry = {
        'type': 'stdin',
        'prompt': content.get('prompt', ''),      # "Enter name: "
        'password': content.get('password', False) # True for getpass()
    }
```

**How stdin capture works:**
- When code calls `input("Enter name: ")`, kernel sends stdin request
- Message contains the prompt text
- password flag indicates if it's hidden input (like `getpass.getpass()`)
- **Note:** This captures the request for input, not the actual input value (for security)

### process_shell_message() - Execution metadata

```python
def process_shell_message(self, msg, kernel_id):
    if msg_type == 'execute_reply':
        log_entry = {
            'status': content.get('status'),  # 'ok' or 'error'
            'execution_count': content.get('execution_count')
        }
```
Captures whether execution succeeded or failed.

## Kernel Discovery

### find_running_kernels()

```python
def find_running_kernels():
    runtime_dir = jupyter_core.paths.jupyter_runtime_dir()
    kernel_files = list(Path(runtime_dir).glob('kernel-*.json'))
```

**How it works:**
- Jupyter stores connection files in a runtime directory (e.g., `~/.local/share/jupyter/runtime/`)
- Each kernel has a JSON file: `kernel-<uuid>.json`
- File contains connection info (ports, keys)
- Script finds all these files to discover active kernels

## Multi-Kernel Monitoring

```python
def monitor_all_kernels(logger):
    monitored_kernels = set()
    
    while logger.running:
        kernels = find_running_kernels()
        
        for kernel in kernels:
            if kernel_id not in monitored_kernels:
                # Start new thread for this kernel
                thread = threading.Thread(
                    target=logger.monitor_kernel,
                    args=(kernel_id, kernel['connection_file']),
                    daemon=True
                )
                thread.start()
```

**Why threading:**
- Each kernel needs continuous monitoring
- Multiple notebooks = multiple kernels
- Threads allow simultaneous monitoring
- Daemon threads auto-cleanup on exit

**Discovery loop:**
- Checks every 2 seconds for new kernels
- If new notebook opened → new kernel detected → new monitoring thread started

## Complete Execution Flow Example

Let's trace what happens when you run:
```python
print("Hello")
x = 5 + 5
x
```

1. **You press Shift+Enter in Jupyter**
2. **Kernel broadcasts on IOPub:**
   - Message type: `execute_input`
   - Content: `{ code: 'print("Hello")\nx = 5 + 5\nx' }`
   - → Logged as cell input
3. **Code executes, print() runs:**
   - Message type: `stream`
   - Content: `{ name: 'stdout', text: 'Hello\n' }`
   - → Logged as stdout
4. **Last expression evaluated:**
   - Message type: `execute_result`
   - Content: `{ data: { 'text/plain': '10' } }`
   - → Logged as output
5. **Shell channel confirms:**
   - Message type: `execute_reply`
   - Content: `{ status: 'ok', execution_count: 1 }`
   - → Logged as execution status

All of this happens in real-time as your code runs!

## Why This Approach Works

- **Non-intrusive:** Doesn't modify your code or notebook
- **Real-time:** Captures as execution happens, not after
- **Complete:** Gets everything the Jupyter UI sees
- **Multiple notebooks:** Monitors all kernels simultaneously
- **Standard protocol:** Uses official Jupyter messaging protocol

The key insight is that Jupyter itself uses these message channels to display output - we're just tapping into the same stream!
