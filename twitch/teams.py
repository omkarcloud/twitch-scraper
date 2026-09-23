"""/twitch/teams/details — a Twitch team with its members and their live status."""
from twitch import parsers as P
from twitch import queries as Q
from twitch.fetch import TwitchNotFound, gql


def details(team):
    data = gql(Q.TEAM_DETAILS, {"name": team})
    node = data.get("team")
    if not isinstance(node, dict) or not node.get("id"):
        raise TwitchNotFound(f"team '{team}' not found")
    return {"team": P.team(node)}
