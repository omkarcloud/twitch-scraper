"""/twitch/channels/* — one channel's profile, live status (single and in
bulk), VODs, clips, schedule, panels, goals, chat settings, channel
points, emotes / cheermotes / badges, VIPs, who is in chat, one viewer's
standing in that chat and the live HLS playlist. Every function takes the
resolved `channel` ref ({"login": ...} or {"id": ...})."""
from twitch import parsers as P
from twitch import queries as Q
from twitch import refs
from twitch.fetch import gql, gql_batch, live_playlist
from twitch.shared import login_of, lower_langs, not_found, user_of


def details(channel):
    """The full channel card: profile, counts, socials, panels, the current
    broadcast settings, the live stream (when live), the last broadcast,
    team and chat settings — one call."""
    data = gql(Q.CHANNEL_DETAILS, refs.user_args(channel))
    return {"channel": P.channel_details(user_of(data, channel))}


def status(channel):
    """Is the channel live right now, with viewers, uptime, title, game and
    tags — one light call, built for polling/alerts."""
    data = gql(Q.CHANNEL_STATUS, refs.user_args(channel))
    return {"channel": P.channel_status(user_of(data, channel))}


def status_batch(channels):
    """Live status for up to 100 channels in one round trip. A login that
    does not exist yields {"login", "error": "not found"} instead of
    failing the batch. Logins and numeric ids may be mixed."""
    logins = [c["login"] for c in channels if c.get("login")]
    ids = [c["id"] for c in channels if c.get("id")]
    ops = []
    if logins:
        ops.append({"query": Q.CHANNELS_STATUS, "variables": {"logins": logins}, "label": "ChannelsStatus"})
    if ids:
        ops.append({"query": Q.CHANNELS_STATUS, "variables": {"ids": ids}, "label": "ChannelsStatusIds"})
    results = gql_batch(ops)
    found = {}
    for data in results:
        for user in data.get("users") or []:
            if isinstance(user, dict) and user.get("id"):
                row = P.channel_status(user)
                found[row["login"]] = row
                found[row["id"]] = row
    rows = []
    for ref in channels:
        key = ref.get("login") or ref.get("id")
        row = found.get(key)
        if row is None:
            rows.append({"id": ref.get("id"), "login": ref.get("login"), "username": None,
                         "link": refs.channel_link(ref.get("login")), "is_live": None, "livestream": None,
                         "error": "not found"})
        else:
            rows.append(row)
    return {
        "count": len(rows),
        "live_count": sum(1 for r in rows if r.get("is_live")),
        "channels": rows,
    }


def videos(channel, type=None, sort="TIME", limit=20, cursor=None):
    """A channel's VODs (past broadcasts, highlights, uploads), newest or
    most viewed first, 100 a page with a cursor."""
    variables = dict(refs.user_args(channel), first=limit, after=cursor, type=type, sort=sort)
    data = gql(Q.CHANNEL_VIDEOS, variables)
    user = user_of(data, channel)
    ref = P.channel_ref(user)
    rows = [P.without_channel(P.video(n)) for n in P.nodes(user.get("videos"))]
    out = {"channel": ref}
    out.update(P.page(user.get("videos"), rows, "videos"))
    return out


def clips(channel, period="LAST_WEEK", sort="VIEWS_DESC", limit=20, cursor=None):
    """A channel's clips for a period (day / week / month / all time), most
    viewed or trending first, with the source VOD offset of each."""
    variables = dict(refs.user_args(channel), first=limit, after=cursor,
                     criteria={"period": period, "sort": sort})
    data = gql(Q.CHANNEL_CLIPS, variables)
    user = user_of(data, channel)
    ref = P.channel_ref(user)
    rows = [P.without_channel(P.clip(n)) for n in P.nodes(user.get("clips"))]
    out = {"channel": ref}
    out.update(P.page(user.get("clips"), rows, "clips"))
    return out


def schedule(channel, start_date=None):
    """The channel's published stream schedule (segments from the week of
    `start_date`, default this week) and any vacation break."""
    variables = dict(refs.user_args(channel), weekday="MONDAY",
                     relativeDate=f"{start_date}T00:00:00Z" if start_date else None)
    data = gql(Q.CHANNEL_SCHEDULE, variables)
    user = user_of(data, channel)
    sched = P.schedule(user.get("channel"))
    return {
        "channel": P.channel_ref(user),
        "has_schedule": sched is not None,
        "schedule": sched,
    }


def panels(channel):
    """The About-page panels (image, link, text) and the social links."""
    data = gql(Q.CHANNEL_PANELS, refs.user_args(channel))
    user = user_of(data, channel)
    rows = P.panels(user.get("panels"))
    return {
        "channel": P.channel_ref(user),
        "socials": P.social_links(user.get("channel")),
        "count": len(rows),
        "panels": rows,
    }


def goals(channel):
    """Creator goals (follower / sub-point targets) with progress."""
    data = gql(Q.CHANNEL_GOALS, refs.user_args(channel))
    user = user_of(data, channel)
    rows = [P.goal(n) for n in P.nodes((user.get("channel") or {}).get("goals"))]
    rows.sort(key=lambda g: (not g["is_active"], g["id"] or ""))
    ref = P.channel_ref(user)
    return {"channel": ref, "active_count": sum(1 for g in rows if g["is_active"]), "count": len(rows), "goals": rows}


def chat_settings(channel):
    """Chat modes (emote-only, subs-only, slow, followers-only, unique),
    the channel rules and any pinned messages."""
    data = gql(Q.CHANNEL_CHAT_SETTINGS, refs.user_args(channel))
    user = user_of(data, channel)
    return {
        "channel": P.channel_ref(user),
        "chat_settings": P.chat_settings(user.get("chatSettings"), user.get("chatColor")),
        "pinned_messages": P.pinned_messages(user.get("channel")),
    }


def points(channel):
    """Channel points: name, icon, custom rewards (cost, limits, cooldown)
    and the emotes viewers can unlock with points."""
    data = gql(Q.CHANNEL_POINTS, refs.user_args(channel))
    user = user_of(data, channel)
    return {"channel": P.channel_ref(user), "channel_points": P.channel_points(user.get("channel"))}


def emotes(channel):
    """Subscription tiers with their emotes, cheermotes and the channel's
    subscriber / bits badges."""
    data = gql(Q.CHANNEL_EMOTES, refs.user_args(channel))
    user = user_of(data, channel)
    products = P.subscription_products(user.get("subscriptionProducts"))
    badges = [P.badge(b) for b in (user.get("broadcastBadges") or []) if isinstance(b, dict)]
    return {
        "channel": P.channel_ref(user),
        "emotes_count": sum(p["emotes_count"] for p in products),
        "subscription_tiers": products,
        "cheermotes": P.cheermotes(user.get("cheer")),
        "badges": badges,
    }


def vips(channel):
    """The channel's VIPs (the moderator list is login-gated upstream)."""
    data = gql(Q.CHANNEL_VIPS, refs.user_args(channel))
    user = user_of(data, channel)
    rows = []
    for edge in (user.get("vips") or {}).get("edges") or []:
        if not isinstance(edge, dict) or not isinstance(edge.get("node"), dict):
            continue
        row = P.channel_ref(edge["node"])
        row.pop("profile_image", None); row.pop("is_partner", None); row.pop("is_affiliate", None)
        row["granted_at"] = P.iso_datetime(edge.get("grantedAt"))
        rows.append(row)
    return {"channel": P.channel_ref(user), "count": len(rows), "vips": rows}


def chatters(channel):
    """Who is in the chat right now: the total and the listed logins per
    role (Twitch lists up to ~1,000 viewers)."""
    data = gql(Q.CHANNEL_CHATTERS, refs.user_args(channel))
    user = user_of(data, channel)
    out = {"channel": P.channel_ref(user), "is_live": isinstance(user.get("stream"), dict)}
    out.update(P.chatters((user.get("channel") or {}).get("chatters")))
    return out


def viewer_card(channel, user):
    """One user's standing in a channel's chat: subscriber months, founder /
    mod / VIP badges, plus their profile."""
    channel_login = login_of(channel)
    user_login = login_of(user)
    data = gql(Q.VIEWER_CARD, {"channelLogin": channel_login, "userLogin": user_login})
    card = P.viewer_card(data)
    if card is None:
        raise not_found(user)
    if card["channel"] is None:
        raise not_found(channel)
    return card


def playback(channel):
    """The live HLS master playlist (signed, short-lived) and every quality
    rendition in it. 404 when the channel is offline."""
    login = login_of(channel)
    data = gql(Q.STREAM_PLAYBACK_TOKEN, {"login": login})
    user = user_of(data, channel)
    token = data.get("streamPlaybackAccessToken")
    if not isinstance(token, dict) or not token.get("value"):
        raise not_found(channel)
    if not isinstance(user.get("stream"), dict):
        from twitch.fetch import TwitchNotFound
        raise TwitchNotFound(f"channel '{login}' is not live")
    playlist_link = f"https://usher.ttvnw.net/api/channel/hls/{login}.m3u8"
    text = live_playlist(login, token)
    out = {"channel": P.channel_ref(user), "is_live": True,
           "viewers_count": P.to_int(user["stream"].get("viewersCount"))}
    out.update(P.playback(token, playlist_link, text))
    return out
