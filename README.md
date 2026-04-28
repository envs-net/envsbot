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

---

## Available Plugins

Below is a complete list of Python plugins in `plugins/` (maybe not completely recent), each with a summary excerpted from its docstring. Only concise summaries are included—full command lists are omitted for clarity.

### **_admin**
> Admin management commands. Provides administrative controls for bot restart, shutdown, and status monitoring.

### **_reg_profile**
> Bot profile initialization plugin. Handles the public XMPP profile (vCard, avatar) for the bot, publishing or updating these automatically on startup or reload, and performs updates only when changes are detected.

### **birthday_notify**
> Birthday notification plugin. Sends automated birthday greetings in rooms, supporting per-room opt-in, caching, multiple date formats, and only notifying users present in the room on their birthday.

### **dice**
> Dice rolling plugin. Provides commands for rolling dice with optional modifiers and success conditions—useful for games or randomization tasks.

### **help**
> Help system for the bot. Offers dynamic help for plugins, commands, and multi-word commands, showing documentation filtered by user role.

### **information**
> Info plugin. Includes commands for fetching the latest Fediverse toots and searching Urban Dictionary.

### **plugins**
> Plugin management commands. Enables administrative loading, unloading, reloading, and listing of plugins at runtime using the PluginManager API.

### **reminder**
> Schedules and manages reminders for users. Allows users to receive automated notifications/messages after specified time intervals.

### **rooms**
> Room management and persistence. Implements administrative tools for managing XMPP MUC rooms, including adding, updating, autojoin settings, and configuration storage in the database.

### **rss**
> RSS Feed watcher plugin. Periodically checks user-specified RSS/Atom feeds and posts new updates to rooms; supports adding/removing feeds per room.

### **sed**
> SED plugin for message correction. Allows users to correct previous messages in chats or rooms using sed-like commands (e.g., s/foo/bar/).

### **status**
> Bot presence and status management. Lets moderators and users view or change the bot's XMPP presence (online, away, DND, etc.) and status message.

### **tell**
> Tell plugin for Envsbot. Enables users to leave messages for others when they're offline, delivering messages the next time the recipient joins the room.

### **tools**
> Utility tools and core bot commands. Offers basic bot health checks (ping/pong), message echo, timezone-aware time/date lookups, UTC, and Unix timestamp conversions.

### **urlcheck**
> URL Check plugin. Watches groupchat messages for URLs and posts HTML page titles or YouTube video info, with configurable room-based enable/disable and spam avoidance.

### **users**
> Users plugin. Handles user registration, per-room nickname and last-seen tracking, JID and nick lookups, and user role management.

### **vcard**
> vCard Lookup plugin. Lets users access vCard details like names, birthdays, organizations, URLs, etc., for themselves or others (when public), and interacts with location-based features.

### **weather**
> Shows current weather for a user’s location. Looks up weather info via wttr.in based on each user’s vCard location; available in groupchats or MUC DMs.

### **xkcd**
> XKCD Comic plugin. Fetches, broadcasts, and allows searching of XKCD comics, with support for random and specific comics, and periodic posting to subscribed rooms.

### **xmpp**
> XMPP utility commands plugin. Supplies various XMPP-related utilities: server ping, service discovery, DNS SRV record lookups, compliance checks, and more via simple commands.

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
- [ ] Add more plugins
- [ ] Improve documentation and usage examples
- [ ] Enhance error handling and logging
- [ ] Choosable Plugins on startup in configuration file
- [X] Improve documentation for configuration file

---

## License

This project is licensed under the **GPL-3.0-only** License. See the [LICENSE](LICENSE) file for details. Future versions of the GPL License are explicitly

