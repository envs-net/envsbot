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

## Project Structure

```
envsbot/
├── envsbot.py               # Main entry point
├── plugins/                 # User and core plugins
├── database/                # Database models and management
├── utils/                   # Utility modules (plugin manager, config, etc.)
├── tests/                   # Test suite for core and plugins
├── README.md
└── LICENSE
```

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
