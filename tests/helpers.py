# PresenceStub for reuse
class DummyXML:
    def findall(self, *args, **kwargs):
        return []


class PresenceStub(dict):
    """
    A test double for a Slixmpp Presence stanza that supports both
    dict and attribute-style access, for compatibility with MUC plugins.
    Usage:
        p = PresenceStub(from_=jid_obj, muc=muc_obj, type="available")
        # use p["from"], p.from_, p.xml, p["xml"], etc.
    """

    def __init__(self, **kwargs):
        super().__init__(kwargs)
        # Populate both key and attribute for every kwarg.
        for key, value in kwargs.items():
            setattr(self, key, value)

        # Alias for handler code that uses pres["from"] instead of pres.from_.
        if "from_" in kwargs:
            setattr(self, "from", kwargs["from_"])
            self["from"] = kwargs["from_"]

        # Always provide a fake XML object for stanza-like access.
        if "xml" not in kwargs:
            self.xml = DummyXML()
            self["xml"] = self.xml

    def __eq__(self, other):
        if isinstance(other, dict):
            return dict.__eq__(self, other)
        return NotImplemented

    def __ne__(self, other):
        result = self.__eq__(other)
        if result is NotImplemented:
            return NotImplemented
        return not result

    def __setattr__(self, key, value):
        super().__setattr__(key, value)
        # Keep dict and attribute access in sync for test mutations.
        if key not in self:
            self[key] = value

    def __getattr__(self, item):
        # Allow attribute-style fallback for dict keys.
        try:
            return self[item]
        except KeyError as exc:
            raise AttributeError(item) from exc


class JIDStub:
    """Small bare/resource JID test double for stanza helpers."""

    def __init__(self, bare: str, resource: str = ""):
        self.bare = bare
        self.resource = resource


class MUCInfoStub:
    """Small MUC payload test double with dict-like get access."""

    def __init__(self, **values):
        self._values = values

    def get(self, key: str):
        return self._values.get(key)


def make_presence_stub(
    room: str,
    nick: str,
    *,
    role: str = "participant",
    jid: str = "user@example.org",
    affiliation: str = "member",
    type_: str = "available",
) -> PresenceStub:
    """Build a reusable MUC presence stanza test double."""
    return PresenceStub(
        from_=JIDStub(room, nick),
        muc=MUCInfoStub(
            role=role,
            jid=JIDStub(jid),
            affiliation=affiliation,
        ),
        type=type_,
    )
