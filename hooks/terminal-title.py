#!/usr/bin/env python3
"""Claude Code hook: set iTerm2 tab/window title, badge, and notifications
from the current Claude Code session name (~/.claude/sessions/{pid}.json)."""
import sys, json, os, subprocess, base64

data = json.load(sys.stdin)
tool = data.get('tool_name', 'working')
tool_input = data.get('tool_input', {})
cwd = data.get('cwd', os.getcwd())
project = cwd.split('/')[-1]

# Find TTY from ancestor processes (needed to write escape sequences to the terminal)
tty_path = None
pid = os.getpid()
for _ in range(10):
    r = subprocess.run(['ps', '-o', 'ppid=', '-p', str(pid)], capture_output=True, text=True)
    pid = r.stdout.strip()
    if not pid or pid == '1':
        break
    r2 = subprocess.run(['ps', '-o', 'tty=', '-p', pid], capture_output=True, text=True)
    tty = r2.stdout.strip()
    if tty and tty != '??' and os.access(f'/dev/{tty}', os.W_OK):
        tty_path = f'/dev/{tty}'
        break

# Read the session name from Claude Code's own session metadata.
# ~/.claude/sessions/{pid}.json holds "name" (set by /rename or plan-approval
# auto-naming) plus "sessionId", so we match on session_id.
session_name = ''
session_id = data.get('session_id') or os.environ.get('CLAUDE_CODE_SESSION_ID', '')
if session_id:
    sessions_dir = os.path.expanduser('~/.claude/sessions')
    try:
        for fn in os.listdir(sessions_dir):
            if not fn.endswith('.json'):
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

# Build detail from tool_input
detail = ''
if tool == 'Bash':
    cmd = tool_input.get('command', '')
    detail = cmd.split('&&')[0].split('|')[0].strip()[:50]
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

# Determine labels based on hook event
stop_mode = os.environ.get('CLAUDE_HOOK_STOP')
if stop_mode:
    icon = '✓'
    tab_title = f'{icon} {project}'
    if session_name:
        tab_title += f' | {session_name}'
    window_title = f'{icon} {project} | 完了'
    badge_text = session_name
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
    # iTerm2: tab title (\033]1;) and window title (\033]2;)
    seq += f'\033]1;{tab_title}\007'
    seq += f'\033]2;{window_title}\007'
    # iTerm2 badge (base64)
    badge_b64 = base64.b64encode(badge_text.encode()).decode()
    seq += f'\033]1337;SetBadgeFormat={badge_b64}\007'
    if notify:
        notify_msg = f'{project}: {session_name}' if session_name else f'{project}: 完了'
        seq += f'\033]9;{notify_msg}\007'
    with open(tty_path, 'w') as f:
        f.write(seq)
