"""Place a desktop shortcut pointing to launcher.bat."""

import os
import subprocess

import ctypes.wintypes
_buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
ctypes.windll.shell32.SHGetFolderPathW(None, 0x0000, None, 0, _buf)
DESKTOP = _buf.value  # CSIDL_DESKTOP — handles OneDrive redirect correctly
SHORTCUT    = os.path.join(DESKTOP, "Kevin Suite.lnk")
BAT_PATH    = r"C:\Users\kevin\projects\kevin-suite\launcher.bat"
WORK_DIR    = r"C:\Users\kevin\projects\kevin-suite"
DESCRIPTION = "Kevin Suite Investment Dashboard"

try:
    import win32com.client
    shell    = win32com.client.Dispatch("WScript.Shell")
    sc       = shell.CreateShortCut(SHORTCUT)
    sc.Targetpath        = BAT_PATH
    sc.WorkingDirectory  = WORK_DIR
    sc.Description       = DESCRIPTION
    sc.save()
    print(f"Shortcut created (win32com): {SHORTCUT}")
except ImportError:
    # Fallback: PowerShell
    ps = f"""
$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{SHORTCUT}")
$Shortcut.TargetPath = "{BAT_PATH}"
$Shortcut.WorkingDirectory = "{WORK_DIR}"
$Shortcut.Description = "{DESCRIPTION}"
$Shortcut.Save()
"""
    result = subprocess.run(
        ["powershell", "-Command", ps],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"Shortcut created (PowerShell): {SHORTCUT}")
    else:
        # Last resort: .bat file on desktop
        fallback = os.path.join(DESKTOP, "Kevin Suite.bat")
        with open(fallback, "w") as f:
            f.write(f'@echo off\nstart "" "{BAT_PATH}"\n')
        print(f"Created .bat launcher on Desktop instead: {fallback}")
