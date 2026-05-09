from __future__ import annotations
import logging, re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("val.soc")

@dataclass
class Threat:
    severity: str
    description: str
    pattern: str
    matched: str
    line_num: int
    auto_action: str = None
    extracted: tuple = field(default_factory=tuple)

SIGNATURES: List[Dict] = [
    {"pattern": re.compile(r"failed\s+password.+?(\d{1,3}(?:\.\d{1,3}){3})", re.I), "severity": "HIGH", "description": "SSH brute-force attempt", "auto_action": "block_ip"},
    {"pattern": re.compile(r"\b(nmap|masscan|zmap)\b", re.I), "severity": "HIGH", "description": "Port scanning tool detected", "auto_action": "scan_ports"},
    {"pattern": re.compile(r"\b(malware|trojan|ransomware|keylogger|rootkit)\b", re.I), "severity": "CRITICAL", "description": "Malware indicator in logs"},
    {"pattern": re.compile(r"(sql injection|union select|'+\s*or\s+1=1)", re.I), "severity": "CRITICAL", "description": "SQL injection attempt"},
    {"pattern": re.compile(r"\b(ddos|denial.of.service|flood)\b", re.I), "severity": "HIGH", "description": "DDoS signature detected"},
    {"pattern": re.compile(r"unauthorized|permission denied|access denied", re.I), "severity": "MEDIUM", "description": "Unauthorized access attempt"},
    {"pattern": re.compile(r"(CVE-\d{4}-\d+)", re.I), "severity": "HIGH", "description": "CVE reference in logs"},
    {"pattern": re.compile(r"(\d{1,3}\.){3}\d{1,3}.{0,30}(scan|probe|sweep)", re.I), "severity": "MEDIUM", "description": "Network scan activity"},
    {"pattern": re.compile(r"sudo|su -|privilege escalat", re.I), "severity": "MEDIUM", "description": "Privilege escalation attempt"},
    {"pattern": re.compile(r"(base64|eval|exec|subprocess).*\(", re.I), "severity": "MEDIUM", "description": "Code execution pattern"},
    {"pattern": re.compile(r"\b(wget|curl).+(http|ftp)", re.I), "severity": "LOW", "description": "Remote file download"},
    {"pattern": re.compile(r"\b(nc|netcat)\b.+-l", re.I), "severity": "HIGH", "description": "Netcat listener detected"},
]

IOC_PATTERNS = {
    "ipv4":   re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "md5":    re.compile(r"\b[0-9a-fA-F]{32}\b"),
    "sha256": re.compile(r"\b[0-9a-fA-F]{64}\b"),
    "domain": re.compile(r"\b(?:[a-z0-9-]+\.)+(?:com|net|org|io|gov|edu|ru|cn)\b", re.I),
    "url":    re.compile(r"https?://\S+"),
    "email":  re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "cve":    re.compile(r"CVE-\d{4}-\d+", re.I),
}


def scan_log_file(log_path: str = "app.log", tail_lines: int = 500) -> List[dict]:
    path = Path(log_path)
    if not path.exists():
        logger.warning("[SOC] Log file not found: %s", log_path)
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-tail_lines:]
    except Exception as e:
        logger.error("[SOC] Cannot read log: %s", e)
        return []
    return _scan_lines(lines)


def analyze_text(text: str) -> List[dict]:
    return _scan_lines(text.splitlines())


def _scan_lines(lines: List[str]) -> List[dict]:
    threats = []
    for line_num, line in enumerate(lines, 1):
        for sig in SIGNATURES:
            m = sig["pattern"].search(line)
            if m:
                threats.append({
                    "severity":    sig["severity"],
                    "description": sig["description"],
                    "pattern":     sig["pattern"].pattern,
                    "matched":     line.strip()[:200],
                    "line_num":    line_num,
                    "auto_action": sig.get("auto_action"),
                    "extracted":   list(m.groups()),
                })
    return threats


def extract_iocs(text: str) -> Dict[str, List[str]]:
    result = {}
    for ioc_type, pat in IOC_PATTERNS.items():
        found = list(set(pat.findall(text)))[:20]
        if found:
            result[ioc_type] = found
    return result


def generate_report(threats: List[dict]) -> str:
    if not threats:
        return "No threats detected."
    by_sev: Dict[str, list] = {}
    for t in threats:
        by_sev.setdefault(t["severity"], []).append(t)
    lines = [f"SOC REPORT -- {len(threats)} threat(s) detected\n"]
    for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        items = by_sev.get(sev, [])
        if items:
            lines.append(f"\n{sev} ({len(items)})")
            for t in items[:10]:
                lines.append(f"  - {t['description']}: {t['matched'][:80]}")
    return "\n".join(lines)


def get_metrics(threats: List[dict]) -> dict:
    total = len(threats)
    by_sev = {}
    for t in threats:
        by_sev[t["severity"]] = by_sev.get(t["severity"], 0) + 1
    return {
        "total":    total,
        "critical": by_sev.get("CRITICAL", 0),
        "high":     by_sev.get("HIGH", 0),
        "medium":   by_sev.get("MEDIUM", 0),
        "low":      by_sev.get("LOW", 0),
        "risk_score": min(100, by_sev.get("CRITICAL", 0) * 25 + by_sev.get("HIGH", 0) * 15 + by_sev.get("MEDIUM", 0) * 5 + by_sev.get("LOW", 0)),
    }