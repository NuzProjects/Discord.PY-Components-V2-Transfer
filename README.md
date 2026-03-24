This module is a drop-in bridge that converts legacy `embed=` / `embeds=` calls (plus classic `View`s) into Components V2 `LayoutView` + `Container` layouts without changing existing cog code. [discordpy.readthedocs](https://discordpy.readthedocs.io/en/stable/interactions/api.html?highlight=discord+actionrow)

## Overview

- Automatically wraps outgoing embeds into a Components V2 **LayoutView** made of **Container**, **TextDisplay**, **MediaGallery**, **Thumbnail**, and **ActionRow** items when those classes are available. [docs.disky](https://docs.disky.me/latest/interactions/componentsv2/)
- Falls back to normal embeds on older discord.py builds that don’t ship Components V2, so you get graceful degradation instead of crashes. [discordpy.readthedocs](https://discordpy.readthedocs.io/en/stable/interactions/api.html?highlight=user+app)

## Features

- One Container per embed:  
  - Thumbnail → `Thumbnail` accessory (floats on the right).  
  - Title/description/fields/footer → single `TextDisplay` with Discord-flavoured markdown.  
  - Main image → single-item `MediaGallery` appended under the text.  
- If you pass a classic **discord.ui.View** via `view=`, its children are migrated into V2 `ActionRow`s and inserted into the first Container so buttons/selects visually live with the embed they belong to. [github](https://github.com/Rapptz/discord.py/blob/master/examples/views/persistent.py)
- Message `content=` is folded into the first embed’s text to satisfy LayoutView’s “no content + layout together” constraint. [discordpy.readthedocs](https://discordpy.readthedocs.io/en/stable/interactions/api.html?highlight=discord+actionrow)
- On HTTP error for the V2 payload, the original request is retried once with plain embeds, avoiding behaviour changes when something breaks upstream. [discordpy.readthedocs](https://discordpy.readthedocs.io/en/stable/interactions/api.html?highlight=discord+actionrow)

## Requirements

- **discord.py** ≥ 2.5, or a fork that exposes:  
  - `discord.ui.LayoutView`, `Container`, `TextDisplay`, `MediaGallery`, `Thumbnail`, `ActionRow`. [discordpy.readthedocs](https://discordpy.readthedocs.io/en/stable/interactions/api.html?highlight=user+app)
- Optional classes (missing ones just degrade visuals): `MediaGalleryItem`, `UnfurledMediaItem`. [docs.disky](https://docs.disky.me/latest/interactions/componentsv2/)

## Installation

```bash
pip install -U discord.py
# or your fork that supports Components V2
```

Drop `components_v2_bridge.py` into your bot’s source tree (e.g. next to your main bot file).

## Usage

Call the bridge **once at startup, before loading cogs or sending any messages**:

```python
import discord
from discord.ext import commands

from components_v2_bridge import enable_components_v2_embed_bridge

enable_components_v2_embed_bridge()  # install the monkey-patches

bot = commands.Bot(command_prefix="!")

@bot.command()
async def demo(ctx: commands.Context):
    embed = discord.Embed(
        title="Hello from Components V2",
        description="This embed is rendered via Container/TextDisplay.",
        colour=discord.Colour.blurple(),
    )
    embed.set_thumbnail(url="https://example.com/thumb.png")
    embed.set_image(url="https://example.com/image.png")

    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Click me"))

    await ctx.send(
        content="Legacy content, now merged into the first embed.",
        embed=embed,
        view=view,
    )

bot.run("TOKEN")
```

With Components V2 available, that call is transparently rewritten to a `LayoutView` containing a Container with text, thumbnail, main image, and migrated buttons; without it, the call behaves exactly like a normal `ctx.send` with embeds and a classic `View`. [docs.disky](https://docs.disky.me/latest/interactions/componentsv2/)

## How It Works (High Level)

- Patched methods: `discord.abc.Messageable.send`, `InteractionResponse.send_message` / `edit_message`, `Webhook.send`, `WebhookMessage.edit`, `Message.edit`. [discordpy.readthedocs](https://discordpy.readthedocs.io/en/stable/interactions/api.html?highlight=discord+actionrow)
- For each call, the bridge:
  - Peeks at `embed=` / `embeds=` and `view=`.  
  - When V2 classes exist, builds one Container per embed and wraps them in a new or existing LayoutView.  
  - Optionally migrates classic View children → `ActionRow`s inside the first Container.  
  - On failure or missing critical classes, leaves kwargs untouched so you keep legacy behaviour. [docs.disky](https://docs.disky.me/latest/interactions/componentsv2/)

## API

```python
from components_v2_bridge import enable_components_v2_embed_bridge, is_patched

enable_components_v2_embed_bridge()
print(is_patched())  # True once installed
```

- `enable_components_v2_embed_bridge()` – Installs the monkey-patches; idempotent.  
- `is_patched() -> bool` – Returns `True` if the bridge is currently active.
