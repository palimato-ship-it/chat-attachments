---
name: chat-attachments
description: Show the Chat compression menu (also Chat compresion), scan local Codex chat attachments, shrink embedded images while preserving originals, retrieve full originals, or configure per-chat automatic conversion after a custom age. Use for chat-history attachment storage, not general disk cleanup or model-context compaction.
---

# Chat Attachments

Use the bundled local MCP tools for the exact selected chat ID from trusted
app/session metadata. Never guess an ID from a title or enable every chat by
default. Respect the user's project-work and validation approval directive.
This plugin operates on locally stored histories, not remote server histories.

## Chat compression menu

When asked for “Chat compression” or “Chat compresion” (case-insensitive), or the
attachment compression menu, show the following numbered menu in the conversation.
Do not scan, convert, configure a policy, or claim live sizes/status merely to show
it. Showing these choices requires no access to the history. This is a conversation
menu, not a native application toolbar or dialog.

1. **Scan this chat** — show history size, attachments and duplicates.
2. **Compress all images now** — prepare conversion of the entire history,
   regardless of image age; skip already processed images.
3. **Enable automatic compression** — images older than **2 days**, only in this chat.
4. **Change the time period** — choose minutes, hours, days or weeks.
5. **Show timer status**.
6. **Disable automatic compression**.
7. **Find a full-resolution original**.

End with “Reply with an option number; for option 4, include the period, for example
‘4 — 7 days’.” Include one short reminder that previews use JPEG quality 20 and
half dimensions, while originals keep their original format and animation.

Treat a number as a menu selection only when this menu is the current pending
choice. When a validation-level approval was asked more recently, a number answers
that approval; do not mistake Level 1 for menu action 1. A menu choice is not
blanket approval to run validation or apply a conversion plan.

Route a selected option as follows, respecting the user's work/validation approval
rule and reusing any already-approved exact scope rather than asking again:

- **1:** `scan_chat(thread_id)`; report the results.
- **2:** scan and `plan_conversion(thread_id)` without an age cutoff. Present the
  actual plan/count and obtain explicit conversion approval before applying it.
- **3:** configure the selected chat for `period: "2 days", enabled: true`, using
  the automatic-policy authorization workflow below.
- **4:** ask for the period if absent. Read `automatic_status` first. Change the
  period while retaining its enabled/disabled state; do not silently enable a
  disabled or unconfigured timer. Report that state clearly. An explicit request
  to enable it with the new period can enable it through the policy workflow.
- **5:** `automatic_status(thread_id)`; report saved settings and last result.
- **6:** read status to keep its period, then disable this chat through the policy
  workflow. Do not remove the app-wide scheduler or affect other chats.
- **7:** ask which image if unclear; scan to identify its content ID, then call
  `original_file`. Return/open the original path, preserving its original extension.

After an action, briefly report its actual result. Show the menu again on request.
Explicit direct requests such as “scan this chat” still go straight to their normal
workflow; do not force the user through the menu each time.

## Automatic conversion requests

Recognize requests such as “automatically resize images older than 2 days in this
chat,” “change the timer to 7 days,” “show this chat's attachment timer,” and
“disable automatic resizing.” The period is the age of each image's message,
not the age of the entire chat and not the polling frequency.

- For status, call `automatic_status(thread_id)`.
- For enable/change, explain that this authorizes future conversions in this chat
  at JPEG quality 20, half width/height, with originals and backups preserved.
  The default image age is 2 days. Accept seconds/minutes/hours/days/weeks,
  including decimals, from one minute through ten years.
- Once the user has explicitly requested that policy and the required work scope
  is approved, call `configure_automatic(thread_id, period, enabled: true,
  approved: true)`. A request with an explicit period is permission for that
  ongoing policy; do not demand approval on every scheduled run.
- For disable, read the current status to retain its period, then call
  `configure_automatic` with that period, `enabled: false`, `approved: true`.
- Report the saved period and enabled state. A policy alone does not prove the
  OS service is running. Installation sets up this user's native timer, which
  polls about once a minute while the user session/computer is running.

Only explicitly enabled chats are processed. The timer requires no unfinished
turns and at least two quiet minutes, rejects writes during conversion, and skips
processed previews. Unknown ages are skipped. If identical original bytes occur
in several genuine messages, all those occurrences must be old enough; compaction
copies do not reset the age. Operational conversion failures pause that chat's
policy; preserve the backup/status and investigate before re-enabling it.

## Manual conversion

1. Call `scan_chat`. Explain unique embedded files, repeated copies, and external
   references. Do not dump raw transcripts/binary data into the conversation.
2. Call `plan_conversion`. Show the selected image count and the quality-20,
   half-dimension JPEG setting, with full originals and backups preserved.
3. Obtain explicit approval of that plan and exact validation scope, then call
   `apply_conversion(plan_id, approved: true)`. Installation is not approval.
4. Report actual sizes and any failure. Cached image cards can require reopening
   or restarting the desktop app. Do not restart or automatically restore history.

JPEG, PNG, GIF and WebP are supported; other listed image formats require a
working Pillow decoder. Animated images use the first frame as a still JPEG;
transparent previews are flattened onto white. Full originals retain their exact
bytes and original format/animation. Documents, logs and other files are unchanged.

For full detail, scan for the content ID and call `original_file`; open the returned
path. To show an unchanged original, prefer a clickable file link or file panel
instead of re-embedding its binary. The per-chat index survives context compaction.

If tools are not loaded, `server.py` is two directories above this skill folder.
Use the Python interpreter recorded in the plugin's `.mcp.json` (its dedicated
virtual environment). CLI actions: `scan --thread-id ID`, `plan --thread-id ID`,
`convert --plan-id ID --approved`, `original --thread-id ID --media-id HASH`,
`automatic --thread-id ID --period "7 days" --approved`,
`automatic --thread-id ID --period "7 days" --disable --approved`, and
`status --thread-id ID`. Newly installed tools/skills may need a new chat or app
restart. The root installer registers the plugin and native background service.
Do not add unapproved tests/reruns or access another host. See the package README
for installation, platform requirements, concurrency limits and recovery.
