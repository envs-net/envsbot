# envsbot

A modular XMPP bot built with Python 3 and slixmpp.

---

**Mirrors:**
- https://git.envs.net/dan/envsbot
- https://github.com/dan-envs/envsbot

---

## 🌐 envs pubnix/tilde

envsbot is developed with the **envs pubnix** environment in mind, but is not limited to it. It takes the tildebot IRC bot as model and hopefully will include all of its features and more (especially for XMPP) in future.

---

## About

envsbot is now in a usable state: the core framework is mostly stable, although probably not bug-free, supports dynamic plugin loading, and provides a structured command system. I can begin developing user plugins to extend the bot's functionality.

- Plugin-based architecture
- Dynamic plugin loading/reloading
- Command decorators
- SQLite-backed database layer
- Test suite for core and plugins

---

## Full Command list

Here's a full command list of all included plugins so far. The commands have to
be prefixed with the configured "prefix" in the configuration file like ",help"
for example. Most of them have aliases or shortcuts, which you can find out
with the "help" command.

Room admins are automatically elevated to Role.MODERATOR for the specific room
if they're not already MODERATORS or higher globally.

---

### Plugin: _reg_profile
**Description:** Bot DB profile, Bot avatar and vCard profile management. Only
run on startup and plugin reload. Only updates, if something changes.

_No commands provided._

---

### Plugin: \_test
**Description:** Testing commands for the bot.

| Command        | Role | Description                                   |
|----------------|------|-----------------------------------------------|
| \_ping          | NONE | Responds with "test pong" for diagnostics     |
| \_reloadtest    | NONE | Verifies command registration after reload    |

---

### Plugin: dice
**Description:** Roll dice with optional modifiers and success conditions.

| Command                                 | Role | Description                                         |
|------------------------------------------|------|-----------------------------------------------------|
| dice \<num\>d\<sides\> \[mod\] \[op\] \[target\]  | USER | Roll dice with optional modifier and success check  (op: \<=, \>=, \>, \<) |

---

### Plugin: help
**Description:** Dynamic help for plugins and commands.

| Command                | Role | Description                                 |
|------------------------|------|---------------------------------------------|
| help \[\<plugin\>\|{prefix}\<command\>\] | NONE | Show help for plugins or commands           |

---

### Plugin: information
**Description:** Acronym, thesaurus, fediverse, and Urban Dictionary lookup.

| Command                        | Role    | Description                                         |
|---------------------------------|---------|-----------------------------------------------------|
| acronym \<word\>                  | USER    | Look up the meaning of an acronym                   |
| fediverse \<@user@instance\>      | USER    | Show the latest public toot from a Fediverse user   |
| thesaurus \<lang\>:\<word\>         | USER    | Look up synonyms for a word in English or German    |
| thesaurus langs                 | USER    | List available thesaurus languages                  |
| udict \<term\>                    | USER    | Search Urban Dictionary for a term                  |

---

### Plugin: plugins
**Description:** Runtime plugin management

| Command                        | Role   | Description                                 |
|---------------------------------|--------|---------------------------------------------|
| plugin info \<plugin\>            | ADMIN  | Show metadata of a plugin                   |
| plugin list                     | ADMIN  | List all plugins grouped by category        |
| plugin load \<plugin\|all\>        | ADMIN  | Load a plugin or all plugins                |
| plugin reload \<plugin\|all\>      | ADMIN  | Reload a plugin or all plugins              |
| plugin unload \<plugin\>           | ADMIN  | Unload a plugin                             |

---

### Plugin: profile
**Description:** User profile management

| Command                                         | Role    | Description                                         |
|--------------------------------------------------|---------|----------------------------------------------------|
| birthday \[nick\]                                  | USER    | Show the birthday of a user and days until next     |
| config birthday \<YYYY-MM-DD\|MM-DD\>               | USER    | Set your birthday in your profile                  |
| config email \<your@email\>                        | USER    | Set your email in your profile                     |
| config fullname \<your full name\>                 | USER    | Set some descriptive name in your profile                 |
| config location \<your location\>                  | USER    | Set your location in your profile                  |
| config pronouns \<your pronouns\>                  | USER    | Set your pronouns in your profile                  |
| config species \<your species\>                    | USER    | Set your species in your profile                   |
| config timezone \<timezone\>                       | USER    | Set your timezone in your profile                  |
| config url add \<url\> \[description\]               | USER    | Add a URL with optional description to your profile|
| config url delete \<url\>                          | USER    | Delete a URL from your profile                     |
| config url list                                  | USER    | List your stored URLs                              |
| email \[nick\]                                     | USER    | Show the email of a user                           |
| fullname \[nick\]                                  | USER    | Show the full name of a user                       |
| profile \[nick\]                                   | USER    | Show all profile data for yourself or another user  |
| pronouns \[nick\]                                  | USER    | Show the pronouns of a user                        |
| species \[nick\]                                   | USER    | Show the species of a user                         |
| urls \[nick\]                                      | USER    | Show the URLs of a user                            |

---

### Plugin: rooms
**Description:** Database-backed room management

| Command                                 | Role    | Description                                               |
|------------------------------------------|---------|----------------------------------------------------------|
| rooms add \<room\_jid\> \<nick\> \[autojoin\]   | ADMIN   | Add a new room configuration to the database             |
| rooms delete \<room\_jid\> \[force\]          | ADMIN   | Remove a room configuration from the database            |
| rooms join \<room\_jid\> \[nick\]             | ADMIN   | Join a room immediately and add it to the database       |
| rooms leave \<room\_jid\>                   | ADMIN   | Leave a joined room immediately (runtime only)           |
| rooms list                               | ADMIN   | Show all rooms stored in the database                    |
| rooms sync                               | ADMIN   | Synchronize runtime rooms with database configuration    |
| rooms update \<room\_jid\> \<field\> \<value\>  | ADMIN   | Update a configuration field of a stored room            |

---

### Plugin: rss
**Description:** RSS/Atom feed watcher and poster

| Command                        | Role      | Description                                               |
|---------------------------------|-----------|----------------------------------------------------------|
| rss add \<url\>                   | MODERATOR | Add an RSS feed to the current room                      |
| rss delete \<url\>                | MODERATOR | Remove an RSS feed from the current room                 |
| rss list                        | MODERATOR | List all RSS feeds configured (globally)       |

---

### Plugin: status
**Description:** Bot presence and status management

| Command                | Role    | Description                                      |
|------------------------|---------|--------------------------------------------------|
| status                 | NONE    | Display the current bot presence and status      |
| status set \<show\> \[message\] | ADMIN   | Change the bot presence and optional status msg  |

---

### Plugin: tools
**Description:** XMPP utility tools (ping, diagnostics, etc.)

| Command                | Role | Description                                   |
|------------------------|------|-----------------------------------------------|
| ping \<jid\|nick\|server\>        | USER | Ping an XMPP JID, room JID/nick, nick or server     |

---

### Plugin: urlcheck
**Description:** URL title and YouTube info fetcher for groupchats

| Command                | Role       | Description                                      |
|------------------------|------------|--------------------------------------------------|
| urlcheck \<on\|off\>      | MODERATOR  | Enable or disable URL checking in a room. Shows info about an URL or YouTube Video if set to "on"         |

---

### Plugin: users
**Description:** User management with caching, nick lookup and logging

| Command                        | Role   | Description                                   |
|---------------------------------|--------|-----------------------------------------------|
| users delete \<jid\>              | ADMIN  | Delete a user                                 |
| users info \<jid\|nick\>           | ADMIN  | Show user info by JID or nickname             |
| users list \[room\_jid\]           | ADMIN  | List all users of a room                      |
| users role \<jid\> \<role\>         | ADMIN  | Update a user's role                          |

---

### Plugin: weather\_time
**Description:** Gives weather and time according to users location

| Command                | Role | Description                                   |
|------------------------|------|-----------------------------------------------|
| time \[nick\]            | USER | Show the current time for a user's timezone   |
| weather \[nick\]         | USER | Show the current weather for a user's location|

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

- [X] Plugin Management Plugin \[core\]
- [X] User Management Plugin \[core\]
- [X] Room Management Plugin \[core\]
- [X] Profile Management Plugin \[core\]
- [ ] Add more plugins
- [ ] Improve documentation and usage examples
- [ ] Enhance error handling and logging
- [ ] Choosable Plugins on startup in configuration file
- [ ] Improve documentation for configuration file

---

## License

This project is licensed under the **GPL-3.0-only** License. See the [LICENSE](LICENSE) file for details. Future versions of the GPL License are explicitly excluded!

---
