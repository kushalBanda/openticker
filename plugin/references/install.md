# Installing this plugin

1. Clone this repo and open it in Claude Code.
2. Claude Code shows a one-time "trust this workspace?" prompt. Accept it.
3. Run this once:
   ```
   /plugin install quant-platform@quant-platform-marketplace
   ```
   This step cannot be skipped. `.claude/settings.json` declares the marketplace and marks the plugin enabled, but Claude Code still requires this explicit install command before it will run a plugin's code — even for a plugin that lives in the same repo. This is a deliberate security boundary, not a bug.
4. After that, the plugin stays installed for this clone. You do not repeat this step on later sessions.
