import subprocess
result = subprocess.run(["git", "push", "origin", "jarvis-master-upgrade"], capture_output=True, text=True)
print(result.stdout)
print(result.stderr)
