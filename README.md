# Chat Attachments — Codex Chat Compression

Shrink image attachments embedded in local Codex chat history while preserving
full originals in their original formats. Includes the **Chat Attachments** plugin
and the **Peli Plugins** marketplace for the Codex desktop app.

Free and open source under the [MIT license](LICENSE). Runs locally; no subscription,
API key, cloud upload, or always-loaded model is needed for compression. Installation
downloads the Python image library. Normal Codex usage has its own requirements.

## What it does

- Scans the selected chat's full stored history, reporting size, unique embedded
  attachments, duplicate copies, external references, and processed images.
- Replaces embedded JPEG, PNG, GIF and WebP images with **quality-20 JPEG previews
  at half width and half height**. Other image formats depend on available decoders.
- Saves full originals, content indexes and operation backups in the project.
- Retrieves originals in their original file format, with animation retained.
- Optionally converts old images automatically, with a different age per chat.
- Provides a numbered menu when you say **Chat compression** or **Chat compresion**.

Only images are resized. Documents, logs, ZIPs and other non-image files are left
unchanged. Animated images become still, first-frame JPEG previews in the chat;
originals retain animation. Transparency is flattened onto white in previews.
This reduces stored image payloads; it does not increase a model's context window.

## Install using the desktop menu

1. Open **Plugins → Add → Add a marketplace**.
2. Enter this repository URL:

   ```text
   https://github.com/palimato-ship-it/chat-attachments
   ```

3. Choose **Peli Plugins**, then install **Chat Attachments**.
4. Complete the one-time local runtime setup below.
5. Restart Codex and say **Chat compression**.

The marketplace file is [`.agents/plugins/marketplace.json`](.agents/plugins/marketplace.json).
The native plugin identity is `chat-attachments@peli-local`; its visible marketplace
name is **Peli Plugins**. This Git marketplace is separate from the official public
OpenAI Plugin Directory. Adding the catalog alone does not install Python/Pillow
or register an operating-system background timer.

### One-time runtime setup after installing through the app

Install Python 3.10 or newer with pip and venv support. Python 3.14 was used for
the original Mac runtime checks. Download this repository's ZIP through
**Code → Download ZIP**, extract it to a permanent folder, and open a terminal there.
Alternatively clone it with Git.

**macOS / Linux:**

```sh
python3 install.py --runtime-only
```

**Windows:**

```powershell
py install.py --runtime-only
```

This creates a private `.venv` folder, installs Pillow from the Python package
index, configures the installed plugin's MCP entry for this computer, and registers
the current user's background timer. Keep the extracted/cloned folder in place:
the timer and virtual environment refer to it. Copying `.venv` to another computer
is not supported; run setup on each computer instead. No chat is enabled for
automatic conversion by installation.

After marketplace updates, rerun this setup if the cached MCP entry was replaced.
If your app uses a custom `CODEX_HOME`, set that environment variable to the same
location when running setup. Setup targets the standard local plugin cache layout.

### Alternative: install with the Codex CLI

If you have Python and the Codex CLI available on PATH, clone/download this repo
and run `python3 install.py` (Windows: `py install.py`). This registers the local
repository as a marketplace, installs the plugin and completes runtime setup.
Use `--runtime-only` instead when you already added this marketplace through the app.

## How to use it

In the chat you want to work on, type:

> Chat compression

Choose an option:

| Option | Action |
| --- | --- |
| 1 | Scan this chat and show sizes/attachments |
| 2 | Compress all images in the entire chat history now, regardless of age |
| 3 | Enable automatic compression for images older than 2 days |
| 4 | Change the image age threshold, retaining the timer's enabled/disabled state |
| 5 | Show this chat's timer settings and last result |
| 6 | Disable automatic compression for this chat |
| 7 | Find a full-resolution original |

For option 4, reply with a period, for example **4 — 7 days**. This menu appears
as text in the conversation; it is not a toolbar added to the application shell.
Manual compression shows a plan and requires approval before rewriting history.
Existing project-specific approval/validation rules still apply. A reply to a
newer approval question answers that question, rather than the earlier menu.

Direct requests also work:

- “Use Chat Attachments to scan this chat.”
- “Resize all images in this chat's entire history now, regardless of age.”
- “Automatically resize images older than 48 hours in this chat.”
- “Change this chat's timer to 7 days.”
- “Show this chat's attachment timer status.”
- “Disable automatic attachment resizing in this chat.”
- “Find the full-resolution original of this image.”

## Automatic conversion

Timers are **off by default and configured per chat**, not across the whole app.
An explicit enable request authorizes future conversions under that saved policy.
Choose a period in seconds, minutes, hours, days or weeks; the minimum is one
minute and the maximum is ten years. The default is **2 days / 48 hours**.

The background process checks about once a minute while your computer/user session
is running. The period controls image age, not how often the process runs. Images
must be old enough and the chat must have completed turns, no unfinished display
turns, and at least two minutes without history writes. New activity defers work.
Processed previews are skipped. Compaction copies do not reset age; reusing the
same original in a new genuine message postpones conversion of those bytes.
Unknown ages are skipped. Failed conversions pause that chat's timer for inspection.

| Platform | Background mechanism | Verification so far |
| --- | --- | --- |
| macOS | User LaunchAgent / launchd | Original timer startup/stop and conversion checked on Mac |
| Windows | Current-user Task Scheduler task | Definition checked on Mac; native installation trial pending |
| Linux | systemd user service and timer | Definition checked on Mac; native installation trial pending |

Linux requires a working systemd user session for automatic installation. Other
Linux init systems are not registered by this installer. This is not a guarantee
that the Codex desktop app exists on every OS version/distribution. It requires
compatible locally persisted Codex JSONL history and display SQLite schemas.
The public packaging installer has not yet had a fresh-machine installation trial.

## Where originals and backups go

Within the selected chat's project folder:

```text
attachments/
  originals/                    Full originals, original extensions
  previews/                     Small JPEG previews
  .chat-attachments/<chat-id>/   Index and operation backups
```

A compressed chat image card downloads its preview. Use the **full-size original**
link or option 7 for the unchanged original file. Some cached image cards require
reopening the chat or restarting the desktop app to refresh.

Timer policies and last-run information are under
`<CODEX_HOME>/chat-attachments/`. Default `CODEX_HOME` is the current user's
`.codex` folder. Local originals and full-history backups intentionally use disk
space even though the active chat payload becomes smaller. They are not uploaded
to this repository or any service by the plugin.

## Limits and recovery

This is an experimental adapter for Codex's local history/display storage, not an
OpenAI-provided storage API. It updates only the selected chat and keeps backups.
Chat history and SQLite are not one atomic transaction, and the plugin does not
hold Codex's own writer lock. Quiet-time and concurrency checks reduce races but
cannot guarantee atomic coordination with a new native turn starting simultaneously.
Schema changes or interrupted writes can require manual investigation.

If a conversion reports `needs_recovery`, preserve the backup and inspect the
operation status before retrying. The timer pauses instead of retrying a failed
conversion. Never blindly restore over newer conversation records. No automatic
history restoration is performed. Remote-server chat histories are not supported.
There is no automatic model-context compaction hook.

To remove only the background registration, run the virtual environment's Python:

```sh
.venv/bin/python plugins/chat-attachments/scheduler.py stop
```

On Windows use `.venv\Scripts\python.exe` instead. Policies, originals and backups
remain. Disable a single chat through option 6; uninstall the plugin through the app
when you want to remove its tools. Disabling/uninstalling the plugin alone does not
promise that an independently registered OS timer has been removed.

For decoder support, CLI commands and additional recovery detail, see the
[plugin documentation](plugins/chat-attachments/README.md).

## Development and privacy

This public repository contains source and manifests only. It excludes chat
histories, uploaded images, originals, backups, local settings, credentials,
virtual environments, generated bytecode and private test reports.

Version 0.2.1 packages the existing conversion/timer engine and conversational
menu for sharing. The engine previously passed seven focused Mac-based scenarios;
that is not a claim of a new clean-machine or Windows/Linux end-to-end test.

Useful references: [OpenAI plugin packaging](https://developers.openai.com/plugins/build/plugins),
[Pillow image formats](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html),
[Windows Task Scheduler](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks-create),
[systemd timers](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html).
