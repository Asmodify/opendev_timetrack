# Building the desktop helper

The helper is one file with no dependencies beyond Python 3.10+.

## Package as a single program (per OS, build on that OS)

```bash
pip install pyinstaller
# Windows: --noconsole hides the window; logs go to %APPDATA%\OpenDevTimeTrack\agent.log
pyinstaller --onefile --noconsole --name timetrack-agent agent/timetrack_agent.py
# macOS
pyinstaller --onefile --name timetrack-agent agent/timetrack_agent.py
```

The program lands in `dist/`. Hand it out through your usual software channel (Intune, Jamf, a shared drive).

## Set up on a worker's computer

1. The worker signs in to the dashboard, accepts the tracking notice and clicks **Link a computer**.
2. On the computer: `timetrack-agent pair --server https://time.your-company.mn --code ABCD-EF12-3456`
3. `timetrack-agent install-autostart` so it starts at every login.

`timetrack-agent status` shows whether it is linked and how long the computer has been idle.

## Notes

- macOS reads idle time with `ioreg`, no extra permission needed. Linux needs `xprintidle`.
- If the helper can't reach the server it keeps retrying; the server ends the open session at the last activity it saw, so offline time is not counted.
- Unsigned programs trigger SmartScreen on Windows and Gatekeeper on macOS. For a company rollout, sign them with the company's code-signing certificate.
