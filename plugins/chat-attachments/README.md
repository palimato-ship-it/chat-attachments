# Chat Attachments 0.2.1

Local Codex attachment previews, full originals and opt-in per-chat timers.
See the [repository installation guide](../../README.md) for marketplace and runtime setup.

Say **Chat compression** (or **Chat compresion**) to show the numbered conversation
menu: scan, compress all now, enable a timer, change its period, show status, disable
it, or find an original. Reply with the option number. Showing the menu changes
nothing; conversion still requires approval of the prepared plan.
Ask “automatically resize images older than 2 days in this chat,” change to
“30 minutes” or “7 days,” ask for timer status, or disable it for the selected chat.
Each chat keeps its own setting; no chat is enabled by installing the plugin.
A saved, approved timer policy authorizes future conversions without per-run prompts.

## Installation and operating systems

From the project root run `python3 install.py` (Windows: `py install.py`). Python
3.10+ with available Pillow wheels, pip/venv and the Codex CLI on PATH are required.
The installer creates a dedicated `.venv`, installs Pillow, refreshes the local
native plugin, and installs the current user's background scheduler:

- macOS: LaunchAgent `peli.chat-attachments.timer` (launchd).
- Windows: same-name Task Scheduler task, interactive current user, no password.
- Linux: same-name systemd user service/timer. A working systemd user session is
  required. Other Linux init systems can run `scheduler.py run --home CODEX_HOME`
  from an existing scheduler, but are not installed automatically.

There is no always-loaded model or API call. A short process checks opted-in chats
about once per minute while the machine/user session is running. It resumes checks
after startup/login. No work happens while the machine is off/asleep. Linux/Windows
startup definitions are checked on Mac; real native startup trials remain pending.
This does not assert Codex desktop availability on every distribution/OS version.
It supports the local Codex history/display schema described below, where present.

The public installer binds the installed MCP cache to this computer’s virtual
environment without writing absolute machine paths into tracked source. Moving
the project or copying it to another OS requires rerunning setup there; a copied
virtual environment is not portable. See the root guide for `--runtime-only`
after installing through the app marketplace. Reopen the app or start a new chat
to load updated tools. No account/API key/network listener is used by the timer.
Pillow is free; dependency installation downloads it from the Python package index.

## Images, age and originals

JPEG, PNG, GIF and WebP become JPEG quality 20 at half the original width/height,
rounded down with a one-pixel minimum. Orientation is applied before resizing;
transparency is flattened onto white. GIF/animated WebP previews use their first
frame. The full original retains exact bytes, extension, transparency and animation.
BMP, TIFF, ICO, AVIF and HEIC/HEIF are recognized, but conversion depends on Pillow
having a decoder (HEIC/HEIF normally needs an additional decoder and is not bundled).
An unsupported decoder pauses automatic conversion for that chat; no silent loss.
Non-image attachments are inventoried but unchanged. Original filenames use safe
content-based names with their original extension when no prior name is indexed.

Age uses actual history record timestamps. All genuine occurrences of identical
bytes must be older than the cutoff, so a new reuse postpones conversion of those
bytes. Compaction copies do not reset age. An unknown timestamp is not treated as
old. Converted previews are skipped using content hashes, not filenames.

Originals: `<project>/attachments/originals`; previews: `attachments/previews`;
indexes/backups: `attachments/.chat-attachments/<thread-id>`.
The `original_file` tool maps original/preview IDs to the full original without
embedding its binary again. A compressed image card downloads its preview; use
the original link/tool for the full original. Cached cards can require reopening.

Timer policies: `<CODEX_HOME>/chat-attachments/schedules/<thread-id>.json`.
`automatic_status` shows period, enabled state and last result; `background.json`
records native service installation, not a guarantee of current liveness.
CLI equivalents are in the skill. To uninstall only the background service, run
its virtual-environment Python with `plugins/chat-attachments/scheduler.py stop`.
Policies and saved attachments remain. Disable individual chats through the tool.

## Concurrency and recovery

This is an experimental local JSONL/display SQLite adapter. Automatic conversion
requires completed turns, no unfinished display turns, and two quiet minutes.
Activity is checked again after preview creation, immediately before rewriting;
any intervening append/rewrite defers it. Plugin operations have cross-platform
process locks. Codex exposes no shared writer lock for this adapter, so these
checks reduce races but do not provide an atomic transaction with a new native
turn starting at the exact same moment. Unknown activity/schema is deferred.
Remote hosts are not supported. No automatic model-context compaction hook is used.

Each operation preserves full `history.jsonl`, changed display records and
`operation.json` before updating the chosen thread and aligning byte offsets.
History and SQLite are not one atomic storage transaction. An interrupted or
failed operation pauses that timer; `prepared`, `writing` or `needs_recovery`
backups block subsequent automatic conversion until inspected. Do not blindly
retry or restore over newer chat records. No automatic restore is performed.
macOS/POSIX files use private permissions; Windows uses the user's existing ACLs.
Backup files contain conversation history and stay local. Timer logs contain safe
codes/exception class names, never transcript bodies. Last-run metadata is replaced
rather than appended indefinitely. Originals/backups intentionally use disk space.

Sources for implementation: [Pillow image formats](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html),
[Windows Task Scheduler](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks-create),
[systemd timers](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html).
