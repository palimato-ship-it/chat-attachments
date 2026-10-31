"""Trusted SessionStart hook: first-use setup and first-response menu context."""
import json
import os
import sys

from runtime import automatic_setup, setup_status

MENU = '''Chat compression
1. Scan this chat — size, attachments and duplicates.
2. Compress all images now — full history; preserve originals.
3. Enable automatic compression — images older than 2 days, only this chat.
4. Change the time period — minutes, hours, days or weeks.
5. Show timer status.
6. Disable automatic compression.
7. Find a full-resolution original.
8. Set up Chat Attachments — install/repair Pillow and the background timer.
Previews: JPEG quality 20, half width and height. Originals retain their format and animation.
Reply with an option number; for option 4 include a period, such as “4 — 7 days”.'''


def on_start(event):
    if event.get('source') not in ('startup', 'clear', 'fork') or event.get('agent_id'):
        return {}
    # The app's own hook trust is the first-use authorization boundary. This
    # optional user setting keeps menu onboarding while disabling auto setup.
    state = setup_status() if os.environ.get('CHAT_ATTACHMENTS_AUTO_SETUP') == '0' else automatic_setup()
    status = ('Setup ready; no chat timers were enabled.' if state['ready'] else
              'Setup is incomplete. Offer option 8; report the returned error code without claiming setup succeeded.')
    context = ('Chat Attachments onboarding for this new chat. Include the menu below once in your first '
               'user-visible response, along with your response to the user. Do not scan history, enable timers, '
               'or compress attachments just to show it. Do not repeat the menu on later turns unless requested. '
               'Respect the user’s project-work approval rules. This hook supplies context, not an empty-chat UI card.\n'
               + status + '\n' + MENU)
    return {'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': context}}


if __name__ == '__main__':
    try:
        event = json.load(sys.stdin)
        result = on_start(event if isinstance(event, dict) else {})
    except Exception as error:
        print('Chat Attachments onboarding failed: ' + type(error).__name__, file=sys.stderr)
        result = {'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext':
                  'Chat Attachments startup setup failed. Offer “Set up Chat Attachments” without claiming success.'}}
    print(json.dumps(result, ensure_ascii=False))
