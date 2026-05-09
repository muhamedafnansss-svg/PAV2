import subprocess
result = subprocess.run(["git", "push", "-u", "origin", "jarvis-master-upgrade"], capture_output=True, text=True)
print(result.stdout)
print(result.stderr)
