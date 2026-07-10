from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any


APP_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = APP_DIR / "data" / "public_tunnel"
TUNNEL_STATE_PATH = RUNTIME_DIR / "state.json"
TUNNEL_LOG_PATH = RUNTIME_DIR / "tunnel.log"
TUNNEL_HISTORY_PATH = RUNTIME_DIR / "history.jsonl"
TUNNEL_KNOWN_HOSTS_PATH = RUNTIME_DIR / "known_hosts"
DEFAULT_FIXED_PUBLIC_URL = "https://banban-ai-dispatch.streamlit.app"
PUBLIC_URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.lhr\.life", re.IGNORECASE)


def access_payload() -> dict[str, Any]:
    port = service_port()
    local_url = f"http://127.0.0.1:{port}"
    lan_ip = _detect_lan_ip()
    lan_url = f"http://{lan_ip}:{port}" if lan_ip else ""
    fixed_url = _fixed_public_url()
    tunnel = _current_tunnel_state()

    public_url = fixed_url or str(tunnel.get("url") or "")
    previous_public_url = str(tunnel.get("previous_url") or "")
    url_changed = bool(tunnel.get("url_changed"))
    local_running = _port_open(port)

    if fixed_url:
        public_status = "online"
        public_mode = "fixed"
        refreshable = False
        hint = "已配置带班分飞机固定公网地址，可以长期使用。"
    elif public_url:
        public_status = "online" if tunnel.get("running") else "offline"
        public_mode = "dynamic"
        refreshable = True
        hint = "带班分飞机临时公网地址已生成；如果打不开，点刷新生成新地址。"
        if url_changed and previous_public_url:
            hint = f"带班分飞机公网地址已更新，旧地址 {previous_public_url} 已失效；请发送当前新地址。"
    elif tunnel.get("running"):
        public_status = "starting"
        public_mode = "dynamic"
        refreshable = True
        hint = "公网隧道正在启动，稍后会自动刷新显示。"
    else:
        public_status = "local_offline" if not local_running else "not_started"
        public_mode = "dynamic"
        refreshable = True
        hint = "当前没有带班分飞机公网地址，点击刷新生成独立临时网址。"
        if not local_running:
            hint = f"本地 {port} 端口未检测到服务；请先打开带班分飞机网页版。"

    return {
        "ok": True,
        "tool_id": "banban_dispatch_web",
        "local_url": local_url,
        "lan_url": lan_url,
        "local_running": local_running,
        "public_url": public_url.rstrip("/"),
        "public_mode": public_mode,
        "public_status": public_status,
        "refreshable": refreshable,
        "previous_public_url": previous_public_url.rstrip("/"),
        "url_changed": url_changed,
        "hint": hint,
        "provider": "localhost.run" if public_mode == "dynamic" else "configured",
        "tunnel": tunnel,
    }


def refresh_public_url() -> dict[str, Any]:
    fixed_url = _fixed_public_url()
    if fixed_url:
        payload = access_payload()
        payload["hint"] = "已配置固定公网地址，不需要刷新。"
        return payload

    ssh = shutil.which("ssh")
    if not ssh:
        raise RuntimeError("本机未找到 ssh，无法生成临时公网网址。")

    port = service_port()
    if not _port_open(port):
        payload = access_payload()
        payload["ok"] = False
        payload["hint"] = f"本地 {port} 端口未启动，无法生成带班分飞机公网网址。"
        return payload

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    previous_url = str(_read_tunnel_state().get("url") or "").rstrip("/")
    _stop_existing_tunnel()
    TUNNEL_LOG_PATH.write_text("", encoding="utf-8")

    command = [
        ssh,
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        f"UserKnownHostsFile={TUNNEL_KNOWN_HOSTS_PATH}",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ExitOnForwardFailure=yes",
        "-R",
        f"80:localhost:{port}",
        "nokey@localhost.run",
    ]

    log_handle = TUNNEL_LOG_PATH.open("ab")
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_handle.close()

    state = {
        "pid": process.pid,
        "url": "",
        "previous_url": previous_url,
        "url_changed": False,
        "provider": "localhost.run",
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "log_path": str(TUNNEL_LOG_PATH),
        "command": " ".join(command),
    }
    _write_tunnel_state(state)

    for _ in range(40):
        time.sleep(1)
        if process.poll() is not None:
            break
        url = _latest_url_from_log()
        if url:
            state["url"] = url
            state["url_changed"] = bool(previous_url and previous_url != url.rstrip("/"))
            if state["url_changed"]:
                _append_tunnel_history(url, previous_url)
            _write_tunnel_state(state)
            break

    payload = access_payload()
    if not payload.get("public_url"):
        payload["public_status"] = "starting" if _pid_alive(process.pid) else "error"
        payload["hint"] = "临时公网地址还没有生成；请稍等几秒后再次刷新。"
    return payload


def service_port() -> int:
    raw = (
        os.environ.get("BANBAN_DISPATCH_PORT")
        or os.environ.get("STREAMLIT_SERVER_PORT")
        or os.environ.get("PORT")
        or "8531"
    )
    return int(raw)


def _fixed_public_url() -> str:
    raw = os.environ.get("BANBAN_DISPATCH_PUBLIC_URL")
    if raw is None:
        raw = DEFAULT_FIXED_PUBLIC_URL
    return str(raw or "").strip().rstrip("/")


def _detect_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass
    return ""


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", int(port))) == 0


def _current_tunnel_state() -> dict[str, Any]:
    state = _read_tunnel_state()
    pid = int(state.get("pid") or 0)
    state["running"] = _pid_alive(pid)
    latest_url = _latest_url_from_log()
    if latest_url:
        previous_url = str(state.get("url") or "")
        if latest_url.rstrip("/") != previous_url.rstrip("/"):
            _append_tunnel_history(latest_url, previous_url)
            state["previous_url"] = previous_url
            state["url_changed"] = bool(previous_url)
        state["url"] = latest_url
        _write_tunnel_state(state)
    return state


def _read_tunnel_state() -> dict[str, Any]:
    if not TUNNEL_STATE_PATH.exists():
        return {}
    try:
        return json.loads(TUNNEL_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_tunnel_state(state: dict[str, Any]) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    TUNNEL_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_tunnel_history(url: str, previous_url: str = "") -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "url": url.rstrip("/"),
        "previous_url": previous_url.rstrip("/"),
        "provider": "localhost.run",
    }
    with TUNNEL_HISTORY_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _latest_url_from_log() -> str:
    if not TUNNEL_LOG_PATH.exists():
        return ""
    try:
        text = TUNNEL_LOG_PATH.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    matches = PUBLIC_URL_PATTERN.findall(text)
    return matches[-1].rstrip("/") if matches else ""


def _stop_existing_tunnel() -> None:
    state = _read_tunnel_state()
    pid = int(state.get("pid") or 0)
    if not _pid_alive(pid):
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return
    for _ in range(10):
        if not _pid_alive(pid):
            return
        time.sleep(0.2)
    try:
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
