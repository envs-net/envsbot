# envsbot

> ⚠️ **Status: Early Development**
> This project is currently in an early development stage and may change
> significantly.
> Features, APIs, and internal structures are not yet considered stable.
>
> It's not nearly complete and very important parts (like user management) are
> still missing

## envs pubnix/tilde
**envsbot** is planned for use on the '**envs**' pubnix / tilde shared Linux
multiuser environment community.

---

**envsbot** is a modular, plugin-driven chat bot framework written in Python.

The project focuses on simplicity, clean architecture, and runtime extensibility.
Features are implemented as plugins which can be dynamically loaded, unloaded, or reloaded without restarting the bot.

envsbot is designed to make it easy to extend functionality while keeping the core bot lightweight and maintainable.

---

## Features

* Plugin-based architecture
* Dynamic plugin loading / unloading
* Command handling system
* Plugin dependency support
* Structured database layer
* Clean and modular codebase

---

## Project Structure

```id="1nyn0j"
envsbot/
│
├─ bot.py                # Main bot runtime
├─ command.py            # Command framework
├─ plugin_manager.py     # Plugin loading and lifecycle management
├─ logging_setup.py      # Logging configuration
│
├─ database/             # Database modules
│   ├─ manager.py
│   ├─ rooms.py
│   └─ users.py
│
├─ plugins/              # Bot plugins
│   ├─ help.py
│   ├─ plugins.py
│   ├─ reg_profile.py
│   ├─ rooms.py
│   └─ status.py
│
├─ config_sample.json    # Example configuration
├─ requirements.txt
└─ README.md
```

---

## Installation

Clone the repository:

```bash
git clone <repository-url>
cd envsbot
```

Create a virtual environment:

```bash
python3 -m venv venv
```

Activate the virtual environment:

**Linux / macOS**

```bash
source venv/bin/activate
```

**Windows**

```bash
venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a configuration file:

```bash
cp config_sample.json config.json
```

Run the bot:

```bash
python bot.py
```

---

## TODO

* [ ] Improve safe hot-reload to prevent module memory leaks
* [ ] Move plugin metadata discovery into `plugin_manager`
* [ ] Add circular dependency detection for plugins
* [ ] Prevent unloading plugins that are required by others
* [ ] Improve plugin validation and error handling
* [ ] Add automated tests
* [ ] Add documentation for plugin development
* [ ] Implement plugin configuration support
* [ ] Add CI pipeline (linting and tests)

---

## License

This project is licensed under the **MIT License**.

