"""vCard plugin persistence helpers."""

async def get_vcard_store(bot):
    return bot.db.users.plugin("vcard")
