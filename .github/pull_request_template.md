## Summary

Describe what this pull request changes and why.

## Type of Change

- [ ] Bug fix
- [ ] New feature
- [ ] Documentation update
- [ ] Test update
- [ ] Refactor / cleanup
- [ ] CI / packaging change

## Areas Affected

- [ ] Commands / help output
- [ ] Plugins / plugin manager
- [ ] Users / roles / permissions
- [ ] Rooms / room feature toggles
- [ ] XMPP messaging / direct messages / MUC PM
- [ ] Database / migrations
- [ ] Audit log
- [ ] Backups / restore
- [ ] Config / reload behavior
- [ ] vCard / avatar
- [ ] RSS / URL checks
- [ ] Tests / CI
- [ ] Documentation
- [ ] Other:

## Testing

- [ ] `PYTHONPATH="$PWD" pytest`
- [ ] `PYTHONPATH="$PWD" pytest --cov=envsbot --cov-report=term-missing`
- [ ] `PYTHONPATH="$PWD" mutmut run`
- [ ] Live XMPP integration test
- [ ] Not run, reason:

## Checklist

- [ ] I tested the relevant behavior.
- [ ] I updated or added tests where appropriate.
- [ ] I updated docs when user-facing behavior changed.
- [ ] I regenerated `docs/commands.md` if command metadata changed.
- [ ] I updated `config_sample.py` if configuration changed.
- [ ] I considered users/roles, permissions, and security implications.
- [ ] I did not commit local secrets, `config.py`, `vcard.py`, databases, backups, or generated test artifacts.
- [ ] I reviewed any AI-generated code before submitting.
