import subprocess
import socket
import json

class BlueTeamToolkit:
    """
    Defensive cybersecurity tools for system auditing and hardening.
    Focuses on vulnerability scanning, port analysis, and firewall configuration.
    """
    
    def __init__(self):
        pass

    def scan_local_ports(self, target="127.0.0.1", start_port=1, end_port=1024):
        """
        Scans local ports to identify potential entry points.
        (A lightweight alternative to full nmap for rapid internal auditing)
        """
        open_ports = []
        # For a rapid scan in Python, we set a very short timeout
        socket.setdefaulttimeout(0.1)
        
        for port in range(start_port, end_port + 1):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex((target, port))
            if result == 0:
                open_ports.append(port)
            sock.close()
            
        return {
            "target": target,
            "open_ports": open_ports,
            "status": "Scan complete"
        }

    def generate_firewall_rules(self, profile="strict"):
        """
        Generates defensive firewall rule scripts based on the requested profile.
        Supports 'strict' (block all ingress except essential) and 'web' (allow 80/443).
        """
        if profile == "strict":
            rules = [
                "sudo ufw default deny incoming",
                "sudo ufw default allow outgoing",
                "sudo ufw allow ssh",
                "sudo ufw enable"
            ]
        elif profile == "web":
            rules = [
                "sudo ufw default deny incoming",
                "sudo ufw default allow outgoing",
                "sudo ufw allow ssh",
                "sudo ufw allow http",
                "sudo ufw allow https",
                "sudo ufw enable"
            ]
        else:
            return "Unknown profile requested."
            
        script = "\n".join(rules)
        return f"#!/bin/bash\n# Generated Firewall Rules ({profile})\n\n{script}\n"

    def analyze_system_logs(self, log_path="/var/log/auth.log", lines=50):
        """
        Basic log analyzer to look for failed SSH attempts or suspicious activity.
        (Linux specific, requires read permissions)
        """
        try:
            cmd = f"tail -n {lines} {log_path} | grep -i 'failed'"
            result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
            
            if not result.stdout.strip():
                return "No suspicious activity found in recent logs."
                
            return f"Suspicious Activity Detected:\n{result.stdout.strip()}"
        except Exception as e:
            return f"Error analyzing logs: {str(e)}"

# Example usage
if __name__ == "__main__":
    bt = BlueTeamToolkit()
    print("Generating Strict Firewall Script:")
    print(bt.generate_firewall_rules("strict"))
