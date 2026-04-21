# envsbot

---

A modular XMPP bot built with Python 3 and slixmpp.

---

**Mirrors:**
- https://git.envs.net/dan/envsbot
- https://github.com/dan-envs/envsbot

---

## 🌐 envs pubnix/tilde

envsbot is developed with the **envs pubnix** environment in mind, but is not limited to it. It takes the tildebot IRC bot as model and hopefully will include all of its features and more (especially in XMPP groupchats and DMs).

---

## About

envsbot is now in a usable state: the core framework is mostly stable, although probably not bug-free, supports dynamic plugin loading, and provides a structured command system. We are now developing new plugins and features on top of it.

- Plugin-based architecture
- Dynamic plugin loading/reloading
- Command decorators
- SQLite-backed database layer
- Test suite for core and plugins

---

## Available Plugins

Below is a list of available plugins in `plugins/` and their descriptions.  
Descriptions are derived from plugin docstrings or, if needed, from code analysis.

- **_admin**  
  Admin management commands.  
  _Exposes administrative commands for bot management, such as restart, shutdown, and status monitoring. Lets OWNERs restart or gracefully shut down the bot, and ADMINs view detailed resource and thread status._

- **_reg_profile**  
  Bot profile initialization plugin.  
  _Manages the bot’s public XMPP profile and its own database profile during startup or reload. No user commands; sets DB profile, vCard, and avatar as needed._

- **birthday_notify**  
  Birthday notification plugin.  
  _Parses user birthday data, stores it, and automatically sends birthday notifications to users in group chats or private messages based on configured dates._

- **dice**  
  Dice rolling plugin.  
  _Roll dice with optional modifiers and success conditions (e.g., `,dice 3d20 -5 >= 30`). Useful for games and randomization._

- **help**  
  📚 Help system for the bot.  
  _Dynamic help for plugins and commands, showing documentation in private messages based on user role._

- **information**  
  Info plugin.  
  _Commands for fetching the latest toots from Fediverse users and Urban Dictionary term search._

- **plugins**  
  Plugin management commands.  
  _Administrative commands for managing plugins at runtime, including load, unload, reload, and listing plugins._

- **profile**  
  Profile management plugin.  
  _Allows users to set and display their NAME, LOCATION, TIMEZONE, BIRTHDAY, PRONOUNS, SPECIES, EMAIL, and personal URLs. Fields can be queried for yourself or others._

- **reminder**  
  Reminder system plugin.  
  _Lets users schedule reminders (one-time or repeating) and sends reminders as private messages or group chat notices at the appropriate time._

- **rooms**  
  Room management and persistence.  
  _Administrative commands for managing XMPP MUC rooms stored in the bot's database, including adding, updating, joining, syncing rooms, and setting rooms to autojoin._

- **rss**  
  RSS Feed watcher plugin.  
  _Checks configured RSS/Atom feeds periodically and posts updates to rooms. Allows adding, deleting, and listing feeds per room._

- **sed**  
  Substitute/replace command plugin.  
  _Enables IRC/Slack-style “s/foo/bar/” corrections for previous messages in the same room or private conversation._

- **status**  
  Bot presence and status management.  
  _Lets moderators change the bot's XMPP presence (online, away, DND, etc.) and allows users to view the bot's current presence and status._

- **tools**  
  Utility tools and core bot commands.  
  _Provides ping/pong, echo, timezone-aware time and date lookup, UTC time, and Unix timestamp conversion. The `{prefix}time` and `{prefix}date` commands are now part of this plugin._

- **urlcheck**  
  URL Check plugin.  
  _Automatic URL title and YouTube info fetching for group chats with spam avoidance/cooldown. Moderators may enable or disable this per room._

- **users**  
  Users plugin.  
  _Manages automatic user registration by JID, tracks last-seen and per-room nickname history, allows lookup and administrative updating of user roles._

- **weather**  
  Weather info plugin.  
  _Shows current weather for a user’s configured location via wttr.in, supporting group chat and private queries._

- **xkcd**  
  XKCD comic plugin.  
  _Fetches and displays XKCD web comics and explanations for given comic numbers or random selections._

- **xmpp**  
  XMPP protocol extension plugin.  
  Handles protocol-specific actions, possibly including advanced XMPP commands, pubsub, message carbons, or XMPP integration features for core bot or plugin functionality.

---

## Installation

1. **Clone the repository:**
   ```sh
   git clone https://github.com/yourusername/envsbot.git
   cd envsbot
   ```

2. **Create a virtual environment (recommended):**
   ```sh
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```sh
   pip install -r requirements.txt
   ```

4. **Configure the bot:**
    - Copy `config_sample.json` to `config.json` and edit with your XMPP credentials and settings.

5. **Run the bot:**
   ```sh
   python envsbot.py
   ```

---

## TODO

- [X] Plugin Management Plugin [core]
- [X] User Management Plugin [core]
- [X] Room Management Plugin [core]
- [X] Profile Management Plugin [core]
- [ ] Add more plugins
- [ ] Improve documentation and usage examples
- [ ] Enhance error handling and logging
- [ ] Choosable Plugins on startup in configuration file
- [X] Improve documentation for configuration file

---

## License

This project is licensed under the **GPL-3.0-only** License. See the [LICENSE](LICENSE) file for details. Future versions of the GPL License are explicitly

