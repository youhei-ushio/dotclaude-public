#!/usr/bin/env python3
"""Claude Code hook: set iTerm2 tab/window title, badge, and notifications
from the current Claude Code session name (~/.claude/sessions/{pid}.json)."""
import base64
import json
import os
import subprocess
import sys


def _osc_safe(s: str) -> str:
    """Strip ESC and BEL to prevent OSC sequence injection."""
    return s.replace('\x1b', '').replace('\x07', '')


try:
    data = json.load(sys.stdin)
except (json.JSONDecodeError, EOFError):
    data = {}

tool = data.get('tool_name', 'working')
tool_input = data.get('tool_input', {})
cwd = data.get('cwd', os.getcwd())
project = os.path.basename(cwd.rstrip('/'))

# Find TTY from ancestor processes (needed to write escape sequences to the terminal)
tty_path = None
pid = str(os.getpid())
for _ in range(10):
    r = subprocess.run(['ps', '-o', 'ppid=', '-p', pid], capture_output=True, text=True)
    pid = r.stdout.strip()
    if not pid or not pid.isdigit() or pid in ('0', '1'):
        break
    r2 = subprocess.run(['ps', '-o', 'tty=', '-p', pid], capture_output=True, text=True)
    tty = ''
    if r2.returncode == 0 and r2.stdout.strip():
        tty = r2.stdout.strip().splitlines()[0]
    if tty and tty != '??' and os.access(f'/dev/{tty}', os.W_OK):
        candidate = os.path.realpath(f'/dev/{tty}')
        if candidate.startswith('/dev/'):
            tty_path = candidate
        break

# Read the session name from Claude Code's own session metadata.
# ~/.claude/sessions/{pid}.json holds "name" (set by /rename or plan-approval
# auto-naming) plus "sessionId", so we match on session_id.
# Full scan is intentional: the file is keyed by the Claude Code process PID
# (not the hook script PID), so we cannot derive the path directly.
# In practice the directory contains only a handful of active-session files.
session_name = ''
session_id = data.get('session_id') or os.environ.get('CLAUDE_CODE_SESSION_ID', '')
if session_id:
    sessions_dir = os.path.expanduser('~/.claude/sessions')
    try:
        for fn in os.listdir(sessions_dir):
            if not fn.endswith('.json') or not fn[:-5].isdigit():
                continue
            try:
                with open(os.path.join(sessions_dir, fn)) as f:
                    sd = json.load(f)
            except (ValueError, IOError):
                continue
            if sd.get('sessionId') == session_id:
                session_name = (sd.get('name') or '').strip()
                break
    except (FileNotFoundError, IOError):
        pass

# Build detail from tool_input.
# Note: Bash command text may contain secrets; it appears only in the window
# title (not badge/notification) and only the first token is used.
detail = ''
if tool == 'Bash':
    cmd = tool_input.get('command', '')
    detail = cmd.split()[0] if cmd.strip() else ''
elif tool in ('Read', 'Write', 'Edit'):
    fp = tool_input.get('file_path', '')
    detail = fp.split('/')[-1] if fp else ''
elif tool == 'Glob':
    detail = tool_input.get('pattern', '')
elif tool == 'Grep':
    detail = tool_input.get('pattern', '')[:40]
elif tool == 'Agent':
    detail = tool_input.get('description', '')[:40]
elif tool == 'Skill':
    detail = tool_input.get('skill', '')

# Sanitize user-controlled strings before embedding in OSC sequences
project = _osc_safe(project)
session_name = _osc_safe(session_name)
detail = _osc_safe(detail)

# Determine labels based on hook event
stop_mode = os.environ.get('CLAUDE_HOOK_STOP') == '1'
if stop_mode:
    icon = '✓'
    tab_title = f'{icon} {project}'
    if session_name:
        tab_title += f' | {session_name}'
    window_title = f'{icon} {project} | 完了'
    badge_text = session_name  # empty string intentionally clears the badge on stop
    notify = True
else:
    icon = '\U0001f916'
    if session_name:
        tab_title = f'{icon} {project} | {session_name}'
    else:
        tab_title = f'{icon} {project}'
    if detail:
        window_title = f'{icon} {project} | {tool}: {detail}'
    else:
        window_title = f'{icon} {project} | {tool}'
    badge_text = session_name
    notify = False

if tty_path:
    seq = ''
    # OSC 1 (icon name / tab title in iTerm2) and OSC 2 (window title)
    seq += f'\033]1;{tab_title}\007'
    seq += f'\033]2;{window_title}\007'
    # iTerm2 badge via OSC 1337 (base64). Non-iTerm2 terminals silently ignore
    # this sequence; tab/window title (OSC 1/2) works on any xterm-compatible terminal.
    badge_b64 = base64.b64encode(badge_text.encode('utf-8')).decode('utf-8')
    seq += f'\033]1337;SetBadgeFormat={badge_b64}\007'
    if notify:
        notify_msg = f'{project}: {session_name}' if session_name else f'{project}: 完了'
        # OSC 9 (notification). Most terminals other than iTerm2 ignore this sequence.
        seq += f'\033]9;{notify_msg}\007'
    try:
        with open(tty_path, 'wb') as f:
            f.write(seq.encode('utf-8'))
    except OSError:
        pass
