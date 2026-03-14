"""
Mock XMPP objects used for testing.
"""


class MockJID:
    """
    Minimal replacement for slixmpp JID objects.
    """

    def __init__(self, jid):
        self.full = jid
        self.bare = jid.split("/")[0]
        self.resource = jid.split("/", 1)[1] if "/" in jid else None

    def __str__(self):
        return self.full


class MockMessage:
    """
    Minimal stand-in for a Slixmpp message stanza used in tests.
    """

    def __init__(self, body="", sender="user@test.local", mtype="chat"):
        self.data = {
            "body": body,
            "from": MockJID(sender),
            "type": mtype,
        }

        # tests inspect this
        self.replies = []

    def __getitem__(self, key):
        return self.data.get(key)

    def __setitem__(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)

    def reply(self, text):
        """
        Simulate Slixmpp reply() behavior for tests.
        """
        self.replies.append(text)
        return self

    def send(self):
        """
        send() is a no-op for the mock but keeps the interface compatible.
        """
        return self
