# Security Policy

EnvsBot is a modular XMPP bot for rooms and direct chats. Security-sensitive
reports should be handled carefully because issues may affect command
permissions, user roles, room administration, direct-message handling, plugin
loading, backups, configuration reloads, audit logs, or database state.

## Supported Versions

Security fixes are generally made against the current `main` branch and the
latest released version. Older releases may not receive separate security
patches unless the maintainer explicitly decides otherwise.

## Reporting a Vulnerability

Please do **not** open a public GitHub issue for security vulnerabilities.
Report security-sensitive issues privately to the project maintainer through the
preferred envs.net contact channel or by email if listed in the repository
metadata.

When reporting, include as much relevant detail as possible:

* Affected EnvsBot version or commit.
* Relevant configuration, with secrets removed.
* Steps to reproduce.
* Expected vs. actual behavior.
* Logs, with JIDs, tokens, passwords, API keys, and private data redacted where
  needed.
* Whether the issue affects authorization, user roles, command execution,
  plugin loading, room permissions, backups, config reloads, audit logs, or
  database state.

## What Counts as Security-Sensitive?

Examples:

* Bypassing owner, superadmin, admin, moderator, or trusted-role checks.
* Modifying roles above the actor's own permission level.
* Treating stored database roles as higher privilege than intended.
* Executing admin-only commands from public rooms or unauthorized direct
  messages.
* Loading, unloading, or reloading protected plugins without permission.
* Unsafe file handling in backups, restore, config, avatar, pin, RSS, URL, or
  plugin paths.
* Exposure of credentials, tokens, private JIDs, `config.py`, `vcard.py`, backup
  archives, or private database contents.
* Audit log behavior that hides privileged changes or stores sensitive secrets.

## Non-Sensitive Bugs

General bugs, usability problems, documentation issues, and feature requests can
be reported using the normal issue templates.

## Responsible Disclosure

Please give the maintainer reasonable time to investigate and prepare a fix
before public disclosure. The maintainer may publish a security note, changelog
entry, or release once a fix is available.
