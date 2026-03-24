"""
Components V2 bridge.

Converts legacy ``embed=`` / ``embeds=`` kwargs into a :class:`discord.ui.LayoutView`
containing :class:`discord.ui.Container` children so existing cog code never needs
to know about Components V2.

When a cog also passes ``view=`` with a classic :class:`discord.ui.View` (buttons,
selects, modals, etc.), the bridge migrates those components into the same
:class:`discord.ui.LayoutView` via :class:`discord.ui.ActionRow` so everything
lands in a single V2 payload.  The original ``view=`` is consumed and replaced.

Usage — call once at bot startup, before any cogs are loaded::

    from components_v2_bridge import enable_components_v2_embed_bridge
    enable_components_v2_embed_bridge()

Requirements:
    discord.py >= 2.5 (or a fork that ships discord.ui.LayoutView / Container /
    TextDisplay / ActionRow).  Older builds that lack these classes fall back
    gracefully to classic embeds — no crash, no data loss.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional, Sequence

import discord

__all__ = ["enable_components_v2_embed_bridge", "is_patched"]

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

_PATCHED = False

# Resolved once at enable-time so every hot-path avoids repeated getattr calls.
_LayoutView: type | None = None
_Container: type | None = None
_TextDisplay: type | None = None
_ActionRow: type | None = None
_MISSING: Any = None


def is_patched() -> bool:
    """Return ``True`` if the bridge has already been installed."""
    return _PATCHED


# ---------------------------------------------------------------------------
# Sentinel helpers
# ---------------------------------------------------------------------------

def _is_missing(value: Any) -> bool:
    """Return ``True`` for ``discord.utils.MISSING`` sentinels."""
    return _MISSING is not None and value is _MISSING


def _unwrap(value: Any, default: Any = None) -> Any:
    """Return *default* when *value* is ``None`` or ``MISSING``, else *value*."""
    if value is None or _is_missing(value):
        return default
    return value


# ---------------------------------------------------------------------------
# Embed helpers
# ---------------------------------------------------------------------------

def _peek_embeds(kwargs: dict) -> List[discord.Embed]:
    """Return the embed list without mutating *kwargs*."""
    out: List[discord.Embed] = []
    e = kwargs.get("embed")
    if isinstance(e, discord.Embed):
        out.append(e)
    es = kwargs.get("embeds")
    if es:
        out.extend(x for x in es if isinstance(x, discord.Embed))
    return out


def _pop_embeds(kwargs: dict) -> List[discord.Embed]:
    """Remove and return all embeds from *kwargs*."""
    out: List[discord.Embed] = []
    e = kwargs.pop("embed", None)
    if isinstance(e, discord.Embed):
        out.append(e)
    es = kwargs.pop("embeds", None)
    if es:
        out.extend(x for x in es if isinstance(x, discord.Embed))
    return out


def _embed_colour(embed: discord.Embed) -> Optional[int]:
    c = embed.color
    if c is None or _is_missing(c):
        return None
    # discord.py Color objects expose .value; raw ints are also valid.
    return int(getattr(c, "value", c))


def _embed_to_markdown(embed: discord.Embed) -> str:
    """Render an :class:`discord.Embed` as a discord-flavoured Markdown string."""
    parts: List[str] = []

    if embed.title:
        parts.append(f"## {embed.title}")

    if embed.description:
        parts.append(embed.description)

    for field in embed.fields:
        name = getattr(field, "name", None) or ""
        value = getattr(field, "value", None) or ""
        if name:
            parts.append(f"**{name}**")
        if value:
            parts.append(value)

    footer_text = getattr(getattr(embed, "footer", None), "text", None)
    if footer_text:
        parts.append(f"-# {footer_text}")

    return "\n\n".join(p for p in parts if p).strip() or "\u200b"


# ---------------------------------------------------------------------------
# Component V2 object builders
# ---------------------------------------------------------------------------

def _build_text_display(content: str) -> Any | None:
    """Instantiate a :class:`discord.ui.TextDisplay` trying known signatures."""
    if _TextDisplay is None:
        return None
    for args, kwargs in (
        ((), {"content": content}),
        ((content,), {}),
        ((), {"text": content}),
    ):
        try:
            return _TextDisplay(*args, **kwargs)
        except TypeError:
            continue
    log.warning("components_v2_bridge: could not instantiate TextDisplay — all signatures failed")
    return None


def _build_container(children: Sequence[Any], *, colour: Optional[int]) -> Any | None:
    """Instantiate a :class:`discord.ui.Container` trying known signatures."""
    if _Container is None:
        return None

    valid = [c for c in children if c is not None]
    if not valid:
        return None

    for args, kwargs in (
        (tuple(valid), {"accent_colour": colour}),
        (tuple(valid), {"accent_color": colour}),
        (tuple(valid), {}),
    ):
        try:
            return _Container(*args, **kwargs)
        except TypeError:
            continue
    log.warning("components_v2_bridge: could not instantiate Container — all signatures failed")
    return None


def _build_layout_view(items: List[Any]) -> Any | None:
    """Wrap *items* in a :class:`discord.ui.LayoutView`."""
    if _LayoutView is None or not items:
        return None
    try:
        layout = _LayoutView()
        for item in items:
            layout.add_item(item)
        return layout
    except Exception:
        log.exception("components_v2_bridge: failed to build LayoutView")
        return None


def _migrate_v1_view(v1_view: Any) -> List[Any]:
    """
    Extract components from a classic :class:`discord.ui.View` and wrap each
    row's worth of items into a :class:`discord.ui.ActionRow`.

    discord.ui.View stores its children in ``._children`` (a list of Items).
    Items carry a ``row`` attribute (0-4).  We group by row, then wrap each
    group in an ActionRow for the V2 LayoutView.

    If ActionRow is unavailable or extraction fails entirely, returns an empty
    list so the caller can decide whether to fall back.
    """
    if _ActionRow is None:
        log.debug("components_v2_bridge: ActionRow unavailable, cannot migrate v1 view")
        return []

    children = getattr(v1_view, "_children", None) or getattr(v1_view, "children", None)
    if not children:
        return []

    # Group by row index preserving insertion order.
    rows: dict[int, List[Any]] = {}
    for item in children:
        row_idx = getattr(item, "row", 0) or 0
        rows.setdefault(row_idx, []).append(item)

    action_rows: List[Any] = []
    for row_idx in sorted(rows):
        items_in_row = rows[row_idx]
        for sig in (
            (tuple(items_in_row), {}),
            ((), {"components": items_in_row}),
            ((), {"children": items_in_row}),
        ):
            args, kw = sig
            try:
                action_rows.append(_ActionRow(*args, **kw))
                break
            except TypeError:
                continue
        else:
            log.warning(
                "components_v2_bridge: could not wrap row %d items into ActionRow — "
                "those components will be dropped",
                row_idx,
            )

    return action_rows


# ---------------------------------------------------------------------------
# Core transform
# ---------------------------------------------------------------------------

def _transform_kwargs(kwargs: dict) -> bool:
    """
    Mutate *kwargs* in-place to use Components V2.

    Returns ``True`` if a V2 transform was applied, ``False`` if the original
    kwargs are left untouched (e.g. no embeds, missing V2 classes).

    Handles three ``view=`` cases:
    - No view        → build a fresh LayoutView from embed containers.
    - LayoutView     → append embed containers to the existing layout.
    - Classic View   → migrate its items into ActionRows, combine with embed
                       containers into a new LayoutView, drop the v1 view.
    """
    # Fast exit — nothing to transform.
    embeds = _peek_embeds(kwargs)
    if not embeds:
        return False

    # If V2 classes are unavailable, fall back gracefully.
    if _LayoutView is None or _Container is None or _TextDisplay is None:
        log.debug("components_v2_bridge: V2 UI classes not available, keeping embeds")
        return False

    existing_view = _unwrap(kwargs.get("view"))
    is_layout_view = existing_view is not None and isinstance(existing_view, _LayoutView)
    is_v1_view = (
        existing_view is not None
        and not is_layout_view
        and isinstance(existing_view, discord.ui.View)
    )

    # Fold content= into the first embed's markdown to avoid
    # "V2 messages cannot mix content and components" errors.
    raw_content = _unwrap(kwargs.get("content"), default="")
    if not isinstance(raw_content, str):
        raw_content = str(raw_content) if raw_content else ""

    # Build a Container per embed.
    containers: List[Any] = []
    for i, embed in enumerate(embeds):
        md = _embed_to_markdown(embed)
        if i == 0 and raw_content:
            md = f"{raw_content}\n\n{md}" if md.strip() else raw_content
        container = _build_container(
            [_build_text_display(md)],
            colour=_embed_colour(embed),
        )
        if container is not None:
            containers.append(container)

    if not containers:
        log.warning("components_v2_bridge: no containers built, falling back to embeds")
        return False

    # Migrate v1 View items into ActionRows (best-effort).
    migrated_rows: List[Any] = []
    if is_v1_view:
        migrated_rows = _migrate_v1_view(existing_view)
        if not migrated_rows:
            log.debug(
                "components_v2_bridge: v1 view migration produced no ActionRows — "
                "buttons/selects will be lost; sending embed containers only"
            )

    # --- Commit: mutate kwargs only after all builders have succeeded ---
    _pop_embeds(kwargs)
    if raw_content:
        kwargs.pop("content", None)

    all_items: List[Any] = containers + migrated_rows

    if is_layout_view:
        # Extend the existing LayoutView in-place.
        for item in all_items:
            existing_view.add_item(item)
        kwargs["view"] = existing_view
    else:
        # Replace v1 view (or absent view) with a fresh LayoutView.
        layout = _build_layout_view(all_items)
        if layout is None:
            log.warning("components_v2_bridge: LayoutView construction failed, falling back")
            return False
        kwargs["view"] = layout

    return True


# ---------------------------------------------------------------------------
# Method patching
# ---------------------------------------------------------------------------

def _patch_async_method(target: Any, method_name: str) -> None:
    original = getattr(target, method_name, None)
    if original is None:
        log.debug("components_v2_bridge: %s.%s not found, skipping", target, method_name)
        return

    # Guard against double-patching an already-wrapped method.
    if getattr(original, "_cv2_patched", False):
        log.debug("components_v2_bridge: %s.%s already patched, skipping", target, method_name)
        return

    async def wrapped(*args, **kwargs):
        pristine = dict(kwargs)
        transformed = _transform_kwargs(kwargs)
        try:
            return await original(*args, **kwargs)
        except discord.HTTPException as exc:
            if transformed:
                # V2 payload was rejected — retry with the original kwargs.
                log.debug(
                    "components_v2_bridge: HTTPException on V2 payload (%s), retrying with embeds",
                    exc.status,
                )
                return await original(*args, **pristine)
            raise  # Not our fault — re-raise for the caller to handle.

    wrapped._cv2_patched = True  # type: ignore[attr-defined]
    setattr(target, method_name, wrapped)
    log.debug("components_v2_bridge: patched %s.%s", target.__name__, method_name)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def enable_components_v2_embed_bridge() -> None:
    """
    Install the Components V2 embed bridge.

    Idempotent — safe to call multiple times; only the first call has any effect.
    Call this once at bot startup **before** loading cogs.
    """
    global _PATCHED, _LayoutView, _Container, _TextDisplay, _ActionRow, _MISSING

    if _PATCHED:
        return

    # Resolve V2 UI classes once so hot-paths skip repeated getattr.
    _LayoutView = getattr(discord.ui, "LayoutView", None)
    _Container = getattr(discord.ui, "Container", None)
    _TextDisplay = getattr(discord.ui, "TextDisplay", None)
    _ActionRow = getattr(discord.ui, "ActionRow", None)
    _MISSING = getattr(discord.utils, "MISSING", None)

    missing_classes = [
        name for name, cls in (
            ("LayoutView", _LayoutView),
            ("Container", _Container),
            ("TextDisplay", _TextDisplay),
            ("ActionRow", _ActionRow),
        )
        if cls is None
    ]
    if missing_classes:
        log.warning(
            "components_v2_bridge: discord.ui is missing %s — "
            "bridge will fall back to classic embeds on all sends. "
            "Upgrade discord.py to >= 2.5 to enable Components V2.",
            ", ".join(missing_classes),
        )

    _patch_async_method(discord.abc.Messageable, "send")
    _patch_async_method(discord.InteractionResponse, "send_message")
    _patch_async_method(discord.InteractionResponse, "edit_message")
    _patch_async_method(discord.Webhook, "send")
    _patch_async_method(discord.WebhookMessage, "edit")
    _patch_async_method(discord.Message, "edit")

    _PATCHED = True
    log.info("components_v2_bridge: installed on 6 methods")
