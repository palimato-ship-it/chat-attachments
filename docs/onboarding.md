# First-use onboarding — 0.3.0

Bundled standard-library MCP setup/status tools remain callable without Pillow.
Approved setup creates a managed environment outside the plugin cache, installs
Pillow, registers the native user timer, and preserves every existing chat policy.
A trusted SessionStart hook supplies a first-response menu and attempts setup
once for this package/version; failed automatic attempts require manual retry.
New chats reuse a ready environment. Resume/compaction do not repeat the menu.
There is no install-time hook used. Hook trust is left to the host’s review flow.
Python remains a prerequisite. The hook cannot create an empty-chat UI card.

Owner approved Low, exactly 3 integration cases, each executed once:

1. `tests/onboarding.py menu` — PASS. Manifest-wired startup command produced menu
   and setup context without touching history; auto-install was opted out for
   this menu-only scenario. Live desktop rendering was not tested.
2. `tests/onboarding.py firstuse` — PASS. Fresh base environment had no Pillow,
   yet MCP setup tools were available. Actual pip setup installed Pillow into a
   separate managed environment; MCP timer status worked through that runtime.
   Native timer registration was requested but stubbed to protect the user service.
3. `tests/onboarding.py repeat` — PASS. Explicit repeat setup preserved enabled/
   disabled policies and custom ages byte-for-byte. Later startup reused setup;
   resumed-chat hook output was empty. Native registration remained stubbed.

Total: 3/3 checks used, no reruns or broad suite. Results/temp environments are
local ignored test artifacts and are not published. No Windows/Linux native
execution, desktop first-response rendering, or new real timer lifecycle test
is claimed by these checks. Native Mac timer registration was covered by the
previous version’s approved lifecycle check.
