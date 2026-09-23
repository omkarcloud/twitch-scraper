"""The 33 Twitch endpoints. Every path is served with and without the
`/twitch` prefix, so code generated against the hosted API on RapidAPI
(paths like /channels/details) runs unchanged against this server.

Params are validated by the marshmallow schemas in twitch/schemas.py — ONE
param per input: `channel` / `user` take a login, numeric id or twitch.tv
link, `game` a category name / slug / id / link, `clip` a slug or link,
`video` an id or link, `team` a name or link. Unknown params are a 400."""
import json

from bottle import request, response, route

from schema_fields import load_query
from scraper_errors import BadRequest, NotFound
from twitch import channels, clips, directory, schemas, search, teams, videos


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The query as unicode strings (bottle 0.12's .get() hands back latin-1
    decoded bytes, so a UTF-8 "Amélie" would arrive as "AmÃ©lie")."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def call(label, schema, fn):
    """Validate with the schema, run the scraper, map errors: bad params ->
    400, missing entity -> 404, transport/blocks -> 500."""
    data, error = load_query(schema, query_dict())
    if error:
        return json_response(error, 400)
    try:
        return json_response(fn(**data))
    except ValueError as e:                # bad id / params
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:                # upstream rejected the request
        return json_response({"error": f"twitch rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Exception as e:                 # retries exhausted / blocked
        return json_response({"error": f"twitch {label} failed: {e}"}, 500)


def mount(path, schema, fn):
    """Serve a scraper function at /path and /twitch/path."""
    def handler():
        return call(path.strip("/"), schema, fn)
    handler.__name__ = "twitch_" + path.strip("/").replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route("/twitch" + path, method="GET")(handler)


ENDPOINTS = [
    ("/channels/details", schemas.ChannelSchema, channels.details),
    ("/search/suggest", schemas.SuggestSchema, search.suggest),
    ("/search", schemas.SearchSchema, search.search),
    ("/search/channels", schemas.SearchListSchema, search.channels),
    ("/search/games", schemas.SearchListSchema, search.games),
    ("/search/videos", schemas.SearchListSchema, search.videos),
    ("/channels/status", schemas.ChannelSchema, channels.status),
    ("/channels/status/batch", schemas.ChannelsSchema, channels.status_batch),
    ("/channels/videos", schemas.ChannelVideosSchema, channels.videos),
    ("/channels/clips", schemas.ChannelClipsSchema, channels.clips),
    ("/clips/details", schemas.ClipSchema, clips.details),
    ("/videos/details", schemas.VideoSchema, videos.details),
    ("/videos/chat", schemas.VideoChatSchema, videos.chat),
    ("/videos/playback", schemas.VideoSchema, videos.playback),
    ("/streams", schemas.StreamsSchema, directory.streams),
    ("/games", schemas.GamesSchema, directory.games),
    ("/games/details", schemas.GameSchema, directory.game_details),
    ("/games/streams", schemas.GameStreamsSchema, directory.game_streams),
    ("/games/videos", schemas.GameVideosSchema, directory.game_videos),
    ("/games/clips", schemas.GameClipsSchema, directory.game_clips),
    ("/tags/search", schemas.TagsSchema, directory.tags),
    ("/channels/schedule", schemas.ScheduleSchema, channels.schedule),
    ("/channels/panels", schemas.ChannelSchema, channels.panels),
    ("/channels/goals", schemas.ChannelSchema, channels.goals),
    ("/channels/chat-settings", schemas.ChannelSchema, channels.chat_settings),
    ("/channels/points", schemas.ChannelSchema, channels.points),
    ("/channels/emotes", schemas.ChannelSchema, channels.emotes),
    ("/channels/vips", schemas.ChannelSchema, channels.vips),
    ("/channels/chatters", schemas.ChannelSchema, channels.chatters),
    ("/channels/viewer-card", schemas.ViewerCardSchema, channels.viewer_card),
    ("/channels/playback", schemas.ChannelSchema, channels.playback),
    ("/teams/details", schemas.TeamSchema, teams.details),
    ("/badges", schemas.EmptySchema, directory.badges),
]

for _path, _schema, _fn in ENDPOINTS:
    mount(_path, _schema, _fn)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, _, _ in ENDPOINTS]})
