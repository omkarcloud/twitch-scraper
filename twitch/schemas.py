"""Marshmallow request schemas for every /twitch/* route. Generic fields
come from the shared schema_fields.py; this module adds the Twitch
resolvers. Every schema's load() output is the kwargs dict its endpoint
function takes.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair):

    channel    a login (xqc), a numeric user id (71092938) OR any twitch.tv channel link
    channels   comma-separated logins / ids / links (max 100)
    user       a login / id / profile link (the viewer whose card is asked for)
    game       a category name (Just Chatting), slug (just-chatting), numeric id
               OR a twitch.tv/directory/category link
    clip       a clip slug OR a clips.twitch.tv / twitch.tv clip link
    video      a numeric video id (2880410519), v2880410519 OR a twitch.tv video link
    team       a team name (otk) OR a twitch.tv/team link
"""
import re

from marshmallow import ValidationError, fields, validate, validates_schema

from schema_fields import (BaseSchema, ChoiceField, DateField, LimitField, QueryField,
                           RefField, StrippedString)
from twitch import refs

_LANG_RE = re.compile(r"^[a-z]{2,3}(-[a-z]{2})?$")


# ---- id-or-link fields -------------------------------------------------------------

class ChannelField(RefField):
    resolver = staticmethod(refs.resolve_channel)


class ChannelListField(RefField):
    resolver = staticmethod(refs.resolve_channels)


class GameField(RefField):
    resolver = staticmethod(refs.resolve_game)


class ClipField(RefField):
    resolver = staticmethod(refs.resolve_clip)


class VideoField(RefField):
    resolver = staticmethod(refs.resolve_video)


class TeamField(RefField):
    resolver = staticmethod(refs.resolve_team)


class CursorField(StrippedString):
    """Opaque next_cursor from the previous page (absent = first page)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)


class LanguagesField(fields.Field):
    """'en, es,pt-br' -> ['en', 'es', 'pt-br'] (Twitch stream language codes, max 10)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        out = []
        for raw in str(value).split(","):
            code = raw.strip().lower().replace("_", "-")
            if not code:
                continue
            if not _LANG_RE.match(code) and code not in ("asl", "other"):
                raise ValidationError(f"'{raw.strip()}' is not a language code (en, es, pt, zh-hk, asl, other).")
            if code not in out:
                out.append(code)
        if len(out) > 10:
            raise ValidationError("At most 10 languages.")
        return out or None


class TagsField(fields.Field):
    """'Vtuber, ASMR' -> ['Vtuber', 'ASMR'] (freeform stream tags, max 10)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        out = []
        for raw in str(value).split(","):
            tag = raw.strip()
            if not tag:
                continue
            if len(tag) > 25 or " " in tag:
                raise ValidationError(f"'{tag}' is not a Twitch tag (one word, up to 25 characters).")
            if tag.lower() not in [t.lower() for t in out]:
                out.append(tag)
        if len(out) > 10:
            raise ValidationError("At most 10 tags.")
        return out or None


_VIDEO_TYPES = {"archive": "ARCHIVE", "highlight": "HIGHLIGHT", "upload": "UPLOAD", "premiere": "PREMIERE_UPLOAD"}
_VIDEO_SORTS = {"time": "TIME", "views": "VIEWS"}
_CLIP_PERIODS = {"day": "LAST_DAY", "week": "LAST_WEEK", "month": "LAST_MONTH", "all": "ALL_TIME"}
_CLIP_SORTS = {"views": "VIEWS_DESC", "trending": "TRENDING"}
_STREAM_SORTS = {"viewers": "VIEWER_COUNT", "recent": "RECENT", "relevance": "RELEVANCE"}


def _limit(default=20, max_size=100):
    return LimitField(default=default, max_size=max_size)


# ---- schemas ---------------------------------------------------------------------------

class EmptySchema(BaseSchema):
    pass


class ChannelSchema(BaseSchema):
    channel = ChannelField()


class ChannelsSchema(BaseSchema):
    channels = ChannelListField()


class ChannelVideosSchema(ChannelSchema):
    type = ChoiceField(_VIDEO_TYPES)
    sort = ChoiceField(_VIDEO_SORTS, load_default="TIME")
    limit = _limit()
    cursor = CursorField()


class ChannelClipsSchema(ChannelSchema):
    period = ChoiceField(_CLIP_PERIODS, load_default="LAST_WEEK")
    sort = ChoiceField(_CLIP_SORTS, load_default="VIEWS_DESC")
    limit = _limit()
    cursor = CursorField()


class ScheduleSchema(ChannelSchema):
    start_date = DateField()


class ViewerCardSchema(ChannelSchema):
    user = ChannelField(metadata={"description": "login, user id or profile link of the viewer"})


class StreamsSchema(BaseSchema):
    sort = ChoiceField(_STREAM_SORTS, load_default="VIEWER_COUNT")
    languages = LanguagesField()
    tags = TagsField()
    limit = _limit(20, 30)
    cursor = CursorField()


class GamesSchema(BaseSchema):
    limit = _limit()
    cursor = CursorField()


class GameSchema(BaseSchema):
    game = GameField()


class GameStreamsSchema(GameSchema):
    sort = ChoiceField(_STREAM_SORTS, load_default="VIEWER_COUNT")
    languages = LanguagesField()
    tags = TagsField()
    limit = _limit()
    cursor = CursorField()


class GameVideosSchema(GameSchema):
    type = ChoiceField(_VIDEO_TYPES)
    sort = ChoiceField(_VIDEO_SORTS, load_default="VIEWS")
    languages = LanguagesField()
    limit = _limit()
    cursor = CursorField()


class GameClipsSchema(GameSchema):
    period = ChoiceField(_CLIP_PERIODS, load_default="LAST_WEEK")
    sort = ChoiceField(_CLIP_SORTS, load_default="VIEWS_DESC")
    languages = LanguagesField()
    limit = _limit()
    cursor = CursorField()


class TagsSchema(BaseSchema):
    query = QueryField(max_length=25)
    limit = _limit(20, 50)


class SearchSchema(BaseSchema):
    query = QueryField(max_length=100)
    limit = _limit(5, 20)


class SearchListSchema(BaseSchema):
    query = QueryField(max_length=100)
    limit = _limit()
    cursor = CursorField()


class SuggestSchema(BaseSchema):
    query = QueryField(max_length=100)


class VideoSchema(BaseSchema):
    video = VideoField()


class VideoChatSchema(VideoSchema):
    offset = fields.Integer(strict=False, load_default=None, validate=validate.Range(min=0),
                            metadata={"description": "seconds into the VOD to start from"})
    cursor = CursorField()

    @validates_schema
    def _offset_or_cursor(self, data, **kwargs):
        if data.get("cursor") and data.get("offset") is not None:
            raise ValidationError("Pass either cursor or offset, not both.", "cursor")


class ClipSchema(BaseSchema):
    clip = ClipField()


class TeamSchema(BaseSchema):
    team = TeamField()
