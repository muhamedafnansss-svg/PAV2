import subprocess
import os
import shlex

class SafeExecutor:
    """
    Executes system commands safely. 
    Provides system-level access to the AI but explicitly blocks destructive commands.
    """
    
    # Absolute blacklist of dangerous commands/arguments
    BLACKLIST = [
        "rm -rf", "rm -r", "mkfs", "dd if=", "> /dev/sda", 
        "format", "del /s /q", "rmdir /s /q", "mkfs.ext4", 
        "shutdown", "reboot", "init 0", "init 6",
        "chmod -R 777 /", "chown -R", ":(){ :|:& };:" # Fork bomb
    ]

    def __init__(self):
        pass

    def _is_safe(self, command_str):
        """Checks if a command contains blacklisted patterns."""
        cmd_lower = command_str.lower()
        for bad_cmd in self.BLACKLIST:
            if bad_cmd in cmd_lower:
                return False, f"Command contains forbidden pattern: '{bad_cmd}'"
        
        return True, ""

    def execute(self, command_str, timeout=30):
        """
        Executes a shell command safely.
        Returns the standard output or error.
        """
        is_safe, reason = self._is_safe(command_str)
        if not is_safe:
            return f"[SECURITY ALERT] Execution blocked. Reason: {reason}"
        
        try:
            # We use shell=True to allow complex commands (like pipes if needed), 
            # but rely on our blacklist to keep it reasonably safe.
            # For strict production, shell=False and shlex parsing is preferred.
            result = subprocess.run(
                command_str, 
                shell=True, 
                text=True, 
                capture_output=True, 
                timeout=timeout
            )
            
            if result.returncode != 0:
                return f"[ERROR] Command failed with exit code {result.returncode}:\n{result.stderr.strip()}"
                
            return result.stdout.strip()
            
        except subprocess.TimeoutExpired:
            return f"[ERROR] Command execution timed out after {timeout} seconds."
        except Exception as e:
            return f"[ERROR] Unexpected execution error: {str(e)}"

# Example usage
if __name__ == "__main__":
    executor = SafeExecutor()
    print("Test Safe Command:", executor.execute("echo 'Jarvis system executor online.'"))
    print("Test Unsafe Command:", executor.execute("rm -rf /"))
