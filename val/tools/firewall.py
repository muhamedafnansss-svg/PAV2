"""
VAL Firewall Builder v14.0 — Cross-Platform Rule Manager
=========================================================
Supports Windows (netsh advfirewall) and Linux (ufw/iptables).
Builds, explains, and optionally applies firewall rules.
Requires POWER or LAB security mode.
"""
from __future__ import annotations

import asyncio
import logging
import platform
import re
import shutil
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger("val.firewall")

IS_WINDOWS = platform.system() == "Windows"


# ─── Rule dataclass ──────────────────────────────────────────────────────────

@dataclass
class FirewallRule:
    action: str          # block | allow | delete
    direction: str       # in | out | both
    protocol: str        # tcp | udp | any
    target: str          # IP, subnet, port, or "any"
    target_type: str     # ip | port | subnet | service
    name: str = ""
    explanation: str = ""

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "direction": self.direction,
            "protocol": self.protocol,
            "target": self.target,
            "target_type": self.target_type,
            "name": self.name,
            "explanation": self.explanation,
        }


# ─── Rule parser (NL → FirewallRule) ─────────────────────────────────────────

_IP_RE   = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?:/\d{1,2})?)\b")
_PORT_RE = re.compile(r"\bport\s+(\d{1,5})\b", re.I)
_PORT2_RE = re.compile(r"\b(\d{1,5})(?:/(?:tcp|udp))?\b")

def parse_firewall_intent(text: str) -> Optional[FirewallRule]:
    """Parse natural language firewall command into a rule."""
    lower = text.lower().strip()

    # Determine action
    if any(w in lower for w in ("block", "deny", "drop", "reject")):
        action = "block"
    elif any(w in lower for w in ("allow", "permit", "open", "accept")):
        action = "allow"
    elif any(w in lower for w in ("delete", "remove", "clear")):
        action = "delete"
    elif "status" in lower or "show" in lower or "list" in lower:
        return FirewallRule(
            action="status", direction="both", protocol="any",
            target="all", target_type="status",
            name="status_check",
            explanation="Show current firewall status and rules",
        )
    else:
        return None

    # Direction
    direction = "in"
    if "outbound" in lower or "outgoing" in lower or "out" in lower:
        direction = "out"
    if "both" in lower:
        direction = "both"

    # Protocol
    protocol = "any"
    if "tcp" in lower:
        protocol = "tcp"
    elif "udp" in lower:
        protocol = "udp"

    # Target: IP or port
    ip_match = _IP_RE.search(text)
    port_match = _PORT_RE.search(text)

    if ip_match:
        target = ip_match.group(1)
        target_type = "subnet" if "/" in target else "ip"
        name = f"VAL_{action}_{target.replace('.', '_').replace('/', '_')}"
    elif port_match:
        target = port_match.group(1)
        target_type = "port"
        name = f"VAL_{action}_port_{target}"
    else:
        # Try to find a bare port number
        port_nums = re.findall(r"\b(22|80|443|8080|8443|3389|3306|5432|21|25|53|110|143|993|995)\b", text)
        if port_nums:
            target = port_nums[0]
            target_type = "port"
            name = f"VAL_{action}_port_{target}"
        else:
            return None

    explanation = _explain_rule(action, direction, protocol, target, target_type)

    return FirewallRule(
        action=action, direction=direction, protocol=protocol,
        target=target, target_type=target_type, name=name,
        explanation=explanation,
    )


def _explain_rule(action: str, direction: str, protocol: str, target: str, target_type: str) -> str:
    """Generate human-readable explanation of what the rule does."""
    action_word = {"block": "Block", "allow": "Allow", "delete": "Remove rule for"}.get(action, action)
    dir_word = {"in": "inbound", "out": "outbound", "both": "inbound and outbound"}.get(direction, direction)
    proto_word = protocol.upper() if protocol != "any" else "all protocols"

    if target_type == "ip":
        return f"{action_word} all {dir_word} traffic ({proto_word}) from/to IP {target}"
    elif target_type == "subnet":
        return f"{action_word} all {dir_word} traffic ({proto_word}) from/to subnet {target}"
    elif target_type == "port":
        svc = _port_service(int(target))
        svc_str = f" ({svc})" if svc else ""
        return f"{action_word} {dir_word} traffic on port {target}{svc_str} ({proto_word})"
    return f"{action_word} {dir_word} traffic for {target}"


def _port_service(port: int) -> str:
    KNOWN = {
        22: "SSH", 80: "HTTP", 443: "HTTPS", 8080: "HTTP-ALT", 8443: "HTTPS-ALT",
        3389: "RDP", 3306: "MySQL", 5432: "PostgreSQL", 21: "FTP", 25: "SMTP",
        53: "DNS", 110: "POP3", 143: "IMAP", 993: "IMAPS", 995: "POP3S",
        6379: "Redis", 27017: "MongoDB", 5900: "VNC",
    }
    return KNOWN.get(port, "")


# ─── Command builders ────────────────────────────────────────────────────────

def build_commands(rule: FirewallRule) -> List[str]:
    """Build OS-specific firewall commands from a rule."""
    if rule.action == "status":
        return _status_commands()
    if IS_WINDOWS:
        return _windows_commands(rule)
    return _linux_commands(rule)


def _status_commands() -> List[str]:
    if IS_WINDOWS:
        return [
            "netsh advfirewall show allprofiles",
            "netsh advfirewall firewall show rule name=all dir=in | findstr /i \"Rule Name\"",
        ]
    if shutil.which("ufw"):
        return ["sudo ufw status verbose"]
    return ["sudo iptables -L -n -v --line-numbers"]


def _windows_commands(rule: FirewallRule) -> List[str]:
    """Build netsh advfirewall commands."""
    cmds = []
    action_map = {"block": "block", "allow": "allow"}
    dirs = ["in", "out"] if rule.direction == "both" else [rule.direction]

    for d in dirs:
        if rule.action == "delete":
            cmds.append(f'netsh advfirewall firewall delete rule name="{rule.name}" dir={d}')
            continue

        fw_action = action_map.get(rule.action, "block")
        base = f'netsh advfirewall firewall add rule name="{rule.name}" dir={d} action={fw_action}'

        if rule.target_type == "ip":
            base += f" remoteip={rule.target}"
        elif rule.target_type == "subnet":
            base += f" remoteip={rule.target}"
        elif rule.target_type == "port":
            proto = rule.protocol if rule.protocol != "any" else "tcp"
            base += f" protocol={proto} localport={rule.target}"

        base += " enable=yes"
        cmds.append(base)

    return cmds


def _linux_commands(rule: FirewallRule) -> List[str]:
    """Build ufw or iptables commands."""
    if shutil.which("ufw"):
        return _ufw_commands(rule)
    return _iptables_commands(rule)


def _ufw_commands(rule: FirewallRule) -> List[str]:
    cmds = []
    if rule.action == "delete":
        if rule.target_type == "port":
            cmds.append(f"sudo ufw delete allow {rule.target}")
            cmds.append(f"sudo ufw delete deny {rule.target}")
        elif rule.target_type in ("ip", "subnet"):
            cmds.append(f"sudo ufw delete allow from {rule.target}")
            cmds.append(f"sudo ufw delete deny from {rule.target}")
        return cmds

    ufw_action = "allow" if rule.action == "allow" else "deny"

    if rule.target_type == "port":
        proto = f"/{rule.protocol}" if rule.protocol != "any" else ""
        cmds.append(f"sudo ufw {ufw_action} {rule.target}{proto}")
    elif rule.target_type in ("ip", "subnet"):
        cmds.append(f"sudo ufw {ufw_action} from {rule.target}")
    return cmds


def _iptables_commands(rule: FirewallRule) -> List[str]:
    cmds = []
    chain = "INPUT" if rule.direction in ("in", "both") else "OUTPUT"
    target = "DROP" if rule.action == "block" else "ACCEPT"

    if rule.action == "delete":
        flag = "-D"
    else:
        flag = "-A"

    if rule.target_type in ("ip", "subnet"):
        cmds.append(f"sudo iptables {flag} {chain} -s {rule.target} -j {target}")
        if rule.direction == "both":
            cmds.append(f"sudo iptables {flag} OUTPUT -d {rule.target} -j {target}")
    elif rule.target_type == "port":
        proto = rule.protocol if rule.protocol != "any" else "tcp"
        cmds.append(f"sudo iptables {flag} {chain} -p {proto} --dport {rule.target} -j {target}")

    return cmds


# ─── Hardened profile generator ──────────────────────────────────────────────

def generate_hardened_profile() -> dict:
    """Generate a hardened firewall profile with best-practice rules."""
    rules = [
        "# VAL Hardened Firewall Profile",
        "# Block all inbound by default, allow essential outbound",
        "",
    ]

    if IS_WINDOWS:
        rules.extend([
            "# Set default policies",
            "netsh advfirewall set allprofiles firewallpolicy blockinbound,allowoutbound",
            "",
            "# Allow essential services",
            'netsh advfirewall firewall add rule name="VAL_Allow_DNS" dir=out action=allow protocol=udp remoteport=53 enable=yes',
            'netsh advfirewall firewall add rule name="VAL_Allow_HTTPS" dir=out action=allow protocol=tcp remoteport=443 enable=yes',
            'netsh advfirewall firewall add rule name="VAL_Allow_HTTP" dir=out action=allow protocol=tcp remoteport=80 enable=yes',
            "",
            "# Block common attack ports inbound",
            'netsh advfirewall firewall add rule name="VAL_Block_Telnet" dir=in action=block protocol=tcp localport=23 enable=yes',
            'netsh advfirewall firewall add rule name="VAL_Block_FTP" dir=in action=block protocol=tcp localport=21 enable=yes',
            'netsh advfirewall firewall add rule name="VAL_Block_RDP_External" dir=in action=block protocol=tcp localport=3389 remoteip=any enable=yes',
            "",
            "# Block known malicious subnets (example)",
            '# netsh advfirewall firewall add rule name="VAL_Block_Suspicious" dir=in action=block remoteip=10.0.0.0/8 enable=yes',
        ])
    else:
        rules.extend([
            "# Set default policies",
            "sudo ufw default deny incoming",
            "sudo ufw default allow outgoing",
            "",
            "# Allow essential services",
            "sudo ufw allow 22/tcp    # SSH",
            "sudo ufw allow 80/tcp    # HTTP",
            "sudo ufw allow 443/tcp   # HTTPS",
            "",
            "# Rate limit SSH",
            "sudo ufw limit 22/tcp",
            "",
            "# Block common attack ports",
            "sudo ufw deny 23/tcp     # Telnet",
            "sudo ufw deny 21/tcp     # FTP",
            "",
            "# Enable firewall",
            "sudo ufw enable",
        ])

    return {
        "platform": "Windows" if IS_WINDOWS else "Linux",
        "rules": rules,
        "script": "\n".join(rules),
        "warning": "⚠️ Review all rules before applying. Some rules may block critical services.",
    }


# ─── Execute commands ─────────────────────────────────────────────────────────

async def execute_firewall_command(cmd: str) -> dict:
    """Execute a single firewall command and return results."""
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        return {
            "command": cmd,
            "stdout": stdout.decode(errors="replace").strip(),
            "stderr": stderr.decode(errors="replace").strip(),
            "exit_code": proc.returncode,
            "success": proc.returncode == 0,
        }
    except asyncio.TimeoutError:
        return {"command": cmd, "error": "Command timed out", "success": False}
    except Exception as e:
        return {"command": cmd, "error": str(e), "success": False}


# ─── Public API ───────────────────────────────────────────────────────────────

def analyze_firewall_request(text: str) -> dict:
    """Analyze a natural language firewall request without executing."""
    if "harden" in text.lower() or "hardened profile" in text.lower():
        profile = generate_hardened_profile()
        return {
            "type": "hardened_profile",
            "explanation": "Generated a hardened firewall profile with best-practice rules",
            **profile,
        }

    rule = parse_firewall_intent(text)
    if rule is None:
        return {"error": "Could not parse firewall intent. Try: 'block ip 1.2.3.4' or 'allow port 443'"}

    commands = build_commands(rule)
    return {
        "type": "rule",
        "rule": rule.to_dict(),
        "commands": commands,
        "explanation": rule.explanation,
        "platform": "Windows" if IS_WINDOWS else "Linux",
        "warning": "⚠️ Commands are shown for review. Use execute=true to apply.",
    }


async def apply_firewall_rule(text: str) -> dict:
    """Parse and execute a firewall rule."""
    analysis = analyze_firewall_request(text)
    if "error" in analysis:
        return analysis

    commands = analysis.get("commands", [])
    if not commands:
        return {"error": "No commands generated"}

    results = []
    for cmd in commands:
        if cmd.startswith("#") or not cmd.strip():
            continue
        r = await execute_firewall_command(cmd)
        results.append(r)

    return {
        **analysis,
        "executed": True,
        "results": results,
        "all_success": all(r.get("success", False) for r in results),
    }
