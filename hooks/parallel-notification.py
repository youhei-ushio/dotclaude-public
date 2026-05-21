#!/usr/bin/env python3
"""
parallel-notification.py

Claude Code Notification / Stop hook with parallel identification.
Shows a custom WPF popup at top-center of the primary screen via powershell.exe.
Stacks vertically when multiple notifications fire simultaneously.
Notification events stay until clicked; Stop/SubagentStop auto-dismiss.
Clicking the popup focuses the corresponding Windows Terminal tab.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# parallel-N: (役割ラベル, アクセント色)
PARALLEL_CONFIG: dict[int, tuple[str, str]] = {
    1: ("feature",         "#2563EB"),
    2: ("hotfix",          "#DC2626"),
    3: ("poc",             "#7C3AED"),
    4: ("issue-authoring", "#0D9488"),
    5: ("feature",         "#0891B2"),
    6: ("refactor",        "#EA580C"),
    7: ("docs-curation",   "#16A34A"),
    8: ("reviewer",        "#475569"),
}

# parallel-N → Windows Terminal タブ index(0-based、wt -w 0 focus-tab で使う)
# タブを並び替えたらここを更新
PARALLEL_TO_TAB_INDEX: dict[int, int] = {
    1: 0,
    2: 1,
    3: 2,
    4: 3,
    5: 4,
    6: 5,
    7: 6,
    8: 7,
}

# 並走 clone のディレクトリ命名規約から N を抽出する正規表現。
# `<project>-parallel-N` 形式を仮定。プロジェクトで命名規約が違う場合はここを書き換える。
PARALLEL_RE = re.compile(r"-parallel-(\d+)")

EVENT_LABEL: dict[str, str] = {
    "Notification": "要応答",
    "Stop":         "完了",
    "SubagentStop": "subagent完了",
}

# イベントごとの表示時間(秒)。0 = 自動消滅なし(クリックで閉じるまで残る)
DURATION_BY_EVENT: dict[str, int] = {
    "Notification": 0,
    "Stop":         4,
    "SubagentStop": 4,
}

# スロット管理(marker file ベース)
SLOT_BASE_TOP_PX        = 60
SLOT_HEIGHT_PX          = 190
SLOT_MARKER_DIR         = Path("/tmp")
SLOT_MARKER_PREFIX      = "claude-popup-slot-"
SLOT_MARKER_SUFFIX      = ".marker"
SLOT_MARKER_GRACE_SEC   = 4 * 3600
MAX_SLOT                = 32

# WPF ポップアップ本体(Light テーマ、click-to-close + tab focus)
WPF_SCRIPT = r"""
param(
    [string]$Title,
    [string]$Subtitle,
    [string]$Body,
    [string]$BgColor,
    [int]$DurationSec = 4,
    [int]$TopOffset   = 60,
    [string]$MarkerPath = '',
    [int]$TabIndex      = -1
)

Add-Type -AssemblyName PresentationFramework

$xamlString = @"
<Window xmlns='http://schemas.microsoft.com/winfx/2006/xaml/presentation'
        xmlns:x='http://schemas.microsoft.com/winfx/2006/xaml'
        WindowStyle='None' AllowsTransparency='True' Background='Transparent'
        Topmost='True' ShowActivated='False' ShowInTaskbar='False'
        SizeToContent='WidthAndHeight' WindowStartupLocation='Manual'
        Left='-10000' Top='-10000'>

  <Border Padding='24' Background='Transparent'>

    <Border Name='Card' CornerRadius='18' Background='#FFFFFF'
            BorderBrush='#71717A' BorderThickness='1' Cursor='Hand'>
      <Border.Effect>
        <DropShadowEffect Color='#1E293B' Opacity='0.15'
                          BlurRadius='32' ShadowDepth='8' Direction='270'/>
      </Border.Effect>

      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width='Auto'/>
          <ColumnDefinition Width='*'/>
        </Grid.ColumnDefinitions>

        <Rectangle Grid.Column='0' Width='5' Fill='$BgColor'
                   RadiusX='2.5' RadiusY='2.5'
                   HorizontalAlignment='Left' VerticalAlignment='Stretch'
                   Margin='12,20,0,20'>
          <Rectangle.Effect>
            <DropShadowEffect Color='$BgColor' Opacity='0.45'
                              BlurRadius='12' ShadowDepth='0'/>
          </Rectangle.Effect>
        </Rectangle>

        <StackPanel Grid.Column='1' Margin='24,24,24,24'>
          <TextBlock Name='TitleBlock' Foreground='#18181B'
                     FontSize='52' FontWeight='Bold' LineHeight='58'
                     FontFamily='Segoe UI Variable Display, Segoe UI'/>
          <TextBlock Name='SubtitleBlock' Foreground='#52525B'
                     FontSize='20' Margin='0,6,0,0' FontWeight='Medium'
                     FontFamily='Segoe UI Variable Text, Segoe UI'/>
          <TextBlock Name='BodyBlock' Foreground='#71717A'
                     FontSize='13' Margin='0,18,0,0'
                     MaxWidth='620' TextWrapping='Wrap'
                     FontFamily='Segoe UI Variable Text, Segoe UI'/>
        </StackPanel>
      </Grid>
    </Border>
  </Border>
</Window>
"@

[xml]$xaml = $xamlString
$reader = New-Object System.Xml.XmlNodeReader $xaml
$window = [Windows.Markup.XamlReader]::Load($reader)

$window.FindName('TitleBlock').Text    = $Title
$window.FindName('SubtitleBlock').Text = $Subtitle
$window.FindName('BodyBlock').Text     = $Body
if ([string]::IsNullOrWhiteSpace($Body)) {
    $window.FindName('BodyBlock').Visibility = 'Collapsed'
}

$window.Add_Loaded({
    $w = $window.ActualWidth
    $screenW = [System.Windows.SystemParameters]::PrimaryScreenWidth
    $window.Left = [Math]::Round(($screenW - $w) / 2)
    $window.Top  = $TopOffset
})

# クリックで該当タブにフォーカス → popup を閉じる
$window.FindName('Card').Add_MouseLeftButtonDown({
    if ($TabIndex -ge 0) {
        try {
            Start-Process -FilePath 'wt.exe' `
                -ArgumentList @('-w', '0', 'focus-tab', '--target', "$TabIndex") `
                -ErrorAction SilentlyContinue
        } catch { }
    }
    $window.Close()
})

# どの経路で閉じても marker を削除
$window.Add_Closed({
    if ($MarkerPath) {
        Remove-Item -Path $MarkerPath -Force -ErrorAction SilentlyContinue
    }
})

# DurationSec <= 0 のときは自動消滅なし
if ($DurationSec -gt 0) {
    $timer = New-Object System.Windows.Threading.DispatcherTimer
    $timer.Interval = [TimeSpan]::FromSeconds($DurationSec)
    $timer.Add_Tick({ $window.Close() })
    $timer.Start()
    $window.Add_Closed({ $timer.Stop() })
}

$window.ShowDialog() | Out-Null
"""


def identify_parallel(cwd: str) -> tuple[int, str, str, str]:
    """Return (parallel_num, label, role, color). parallel_num=0 if unknown."""
    m = PARALLEL_RE.search(cwd or "")
    if not m:
        return (0, "P?", "unknown", "#475569")
    n = int(m.group(1))
    role, color = PARALLEL_CONFIG.get(n, ("unknown", "#475569"))
    return (n, f"P{n}", role, color)


def ps_escape(s: str) -> str:
    """Escape single quotes for PowerShell single-quoted strings."""
    return (s or "").replace("'", "''")


def _marker_path(slot: int) -> Path:
    return SLOT_MARKER_DIR / f"{SLOT_MARKER_PREFIX}{slot}{SLOT_MARKER_SUFFIX}"


def _to_windows_path(linux_path: Path) -> str:
    """Convert WSL path to Windows UNC path for PowerShell."""
    try:
        result = subprocess.run(
            ["wslpath", "-w", str(linux_path)],
            capture_output=True, text=True, check=True, timeout=5,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError):
        distro = os.environ.get("WSL_DISTRO_NAME", "Ubuntu-24.04")
        linux_path_str = str(linux_path).replace("/", "\\")
        return f"\\\\wsl.localhost\\{distro}{linux_path_str}"


def claim_slot() -> tuple[int, Path]:
    """Atomically claim the lowest free slot via marker file creation."""
    now = time.time()

    try:
        pattern = f"{SLOT_MARKER_PREFIX}*{SLOT_MARKER_SUFFIX}"
        for marker in SLOT_MARKER_DIR.glob(pattern):
            try:
                if now - marker.stat().st_mtime > SLOT_MARKER_GRACE_SEC:
                    marker.unlink(missing_ok=True)
            except OSError:
                pass
    except OSError:
        pass

    for slot in range(MAX_SLOT):
        marker = _marker_path(slot)
        try:
            fd = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.close(fd)
            return slot, marker
        except FileExistsError:
            continue
        except OSError:
            return 0, _marker_path(0)

    return 0, _marker_path(0)


def show_popup(title: str, subtitle: str, body: str, bg_color: str,
               duration_sec: int = 4, tab_index: int = -1) -> None:
    """Spawn PowerShell WPF popup at the next available stacking slot."""
    slot, marker = claim_slot()
    top_offset = SLOT_BASE_TOP_PX + slot * SLOT_HEIGHT_PX
    win_marker = _to_windows_path(marker)

    invocation = (
        f"& {{ {WPF_SCRIPT} }} "
        f"-Title '{ps_escape(title)}' "
        f"-Subtitle '{ps_escape(subtitle)}' "
        f"-Body '{ps_escape(body)}' "
        f"-BgColor '{bg_color}' "
        f"-DurationSec {duration_sec} "
        f"-TopOffset {top_offset} "
        f"-MarkerPath '{ps_escape(win_marker)}' "
        f"-TabIndex {tab_index}"
    )
    encoded = base64.b64encode(invocation.encode("utf-16-le")).decode("ascii")
    try:
        subprocess.Popen(
            [
                "powershell.exe",
                "-ExecutionPolicy", "Bypass",
                "-NoProfile",
                "-Sta",
                "-WindowStyle", "Hidden",
                "-EncodedCommand", encoded,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (FileNotFoundError, OSError) as e:
        marker.unlink(missing_ok=True)
        print(f"[parallel-notification] popup failed: {e}", file=sys.stderr)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}

    cwd     = payload.get("cwd", "")
    event   = payload.get("hook_event_name", "")
    message = (payload.get("message") or "").strip()

    parallel_num, label, role, color = identify_parallel(cwd)
    event_jp = EVENT_LABEL.get(event, event or "?")

    title    = f"{label}  {role}"
    subtitle = event_jp
    body     = message[:200] if message else ""

    duration  = DURATION_BY_EVENT.get(event, 4)
    tab_index = PARALLEL_TO_TAB_INDEX.get(parallel_num, -1)

    show_popup(title, subtitle, body, color,
               duration_sec=duration, tab_index=tab_index)
    return 0


if __name__ == "__main__":
    sys.exit(main())