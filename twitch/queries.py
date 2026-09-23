"""Raw GraphQL documents for gql.twitch.tv (no persisted hashes: Twitch
accepts full query text from its first-party client ids, so nothing here
rotates). Field names were verified live 2026-09-23; fetch.py turns a
schema error into TwitchUpstreamError("Twitch changed its schema ...") so a
rename surfaces as a 502 with the field named, never as a silent null.

Argument caps (upstream): `first` 1-100 on every connection except the
site-wide `streams` (1-30); `users(logins:)` accepts 100+ logins. The VOD
chat replay ignores `first` and always answers one ~50-60 message chunk
(every edge in it carries the same cursor), so it takes no page size.
"""

# ---- fragments -----------------------------------------------------------------------

USER_REF = """
fragment UserRef on User {
  id login displayName
  profileImageURL(width: 150)
  roles { isPartner isAffiliate }
}
"""

GAME_REF = """
fragment GameRef on Game {
  id name displayName slug
  boxArtURL(width: 285, height: 380)
}
"""

STREAM_CARD = """
fragment StreamCard on Stream {
  id title viewersCount createdAt type language isMature
  averageFPS bitrate codec height width
  previewImageURL(width: 640, height: 360)
  game { ...GameRef }
  freeformTags { name }
  contentClassificationLabels { id }
  broadcaster { ...UserRef }
}
"""

VIDEO_CARD = """
fragment VideoCard on Video {
  id title description viewCount lengthSeconds publishedAt createdAt
  language broadcastType status
  previewThumbnailURL(width: 640, height: 360)
  animatedPreviewURL
  game { ...GameRef }
  owner { ...UserRef }
  contentTags { id localizedName }
}
"""

CLIP_CARD = """
fragment ClipCard on Clip {
  id slug title url viewCount durationSeconds createdAt language isFeatured
  thumbnailURL(width: 480, height: 272)
  videoOffsetSeconds
  broadcaster { ...UserRef }
  curator { ...UserRef }
  game { ...GameRef }
  video { id }
}
"""

GAME_CARD = """
fragment GameCard on Game {
  ...GameRef
  viewersCount followersCount
  tags(tagType: CONTENT) { id localizedName }
}
"""

BADGE = """
fragment Badge on Badge {
  id setID version title description clickAction clickURL
  imageURL(size: DOUBLE)
}
"""

_STREAM_DEPS = USER_REF + GAME_REF + STREAM_CARD
_VIDEO_DEPS = USER_REF + GAME_REF + VIDEO_CARD
_CLIP_DEPS = USER_REF + GAME_REF + CLIP_CARD


# ---- channels ----------------------------------------------------------------------------

CHANNEL_DETAILS = _STREAM_DEPS + """
query ChannelDetails($login: String, $id: ID) {
  user(login: $login, id: $id) {
    id login displayName description createdAt updatedAt
    profileImageURL(width: 600)
    bannerImageURL offlineImageURL primaryColorHex chatColor language
    roles { isPartner isAffiliate isStaff }
    followers { totalCount }
    broadcastSettings { title language isMature game { ...GameRef } }
    lastBroadcast { id title startedAt game { ...GameRef } }
    primaryTeam { id name displayName }
    stream { ...StreamCard }
    channel {
      id founderBadgeAvailability
      socialMedias { id name title url }
    }
    videos(first: 1) { totalCount }
    chatSettings {
      isEmoteOnlyModeEnabled isFastSubsModeEnabled isSubscribersOnlyModeEnabled
      isUniqueChatModeEnabled slowModeDurationSeconds followersOnlyDurationMinutes
      requireVerifiedAccount chatDelayMs rules
    }
    panels {
      id type
      ... on DefaultPanel { title description linkURL imageURL }
    }
  }
}
"""

CHANNEL_STATUS = _STREAM_DEPS + """
query ChannelStatus($login: String, $id: ID) {
  user(login: $login, id: $id) {
    ...UserRef
    followers { totalCount }
    lastBroadcast { id title startedAt game { ...GameRef } }
    stream { ...StreamCard }
  }
}
"""

CHANNELS_STATUS = _STREAM_DEPS + """
query ChannelsStatus($logins: [String!], $ids: [ID!]) {
  users(logins: $logins, ids: $ids) {
    ...UserRef
    followers { totalCount }
    lastBroadcast { startedAt }
    stream { ...StreamCard }
  }
}
"""

CHANNEL_VIDEOS = _VIDEO_DEPS + """
query ChannelVideos($login: String, $id: ID, $first: Int!, $after: Cursor, $type: BroadcastType, $sort: VideoSort) {
  user(login: $login, id: $id) {
    ...UserRef
    videos(first: $first, after: $after, type: $type, sort: $sort) {
      totalCount
      edges { cursor node { ...VideoCard } }
      pageInfo { hasNextPage }
    }
  }
}
"""

CHANNEL_CLIPS = _CLIP_DEPS + """
query ChannelClips($login: String, $id: ID, $first: Int!, $after: Cursor, $criteria: UserClipsInput) {
  user(login: $login, id: $id) {
    ...UserRef
    clips(first: $first, after: $after, criteria: $criteria) {
      edges { cursor node { ...ClipCard } }
      pageInfo { hasNextPage }
    }
  }
}
"""

CHANNEL_SCHEDULE = USER_REF + GAME_REF + """
query ChannelSchedule($login: String, $id: ID, $weekday: String, $relativeDate: Time) {
  user(login: $login, id: $id) {
    ...UserRef
    channel {
      schedule {
        id
        interruption { startAt endAt }
        segments(startingWeekday: $weekday, relativeDate: $relativeDate) {
          id title startAt endAt isCancelled hasReminder
          categories { ...GameRef }
        }
      }
    }
  }
}
"""

CHANNEL_PANELS = USER_REF + """
query ChannelPanels($login: String, $id: ID) {
  user(login: $login, id: $id) {
    ...UserRef
    channel { socialMedias { id name title url } }
    panels {
      id type
      ... on DefaultPanel { title description linkURL imageURL }
    }
  }
}
"""

CHANNEL_GOALS = USER_REF + """
query ChannelGoals($login: String, $id: ID) {
  user(login: $login, id: $id) {
    ...UserRef
    followers { totalCount }
    channel {
      goals(first: 50) {
        edges { node { id state contributionType targetContributions currentContributions description } }
      }
    }
  }
}
"""

CHANNEL_CHAT_SETTINGS = USER_REF + """
query ChannelChatSettings($login: String, $id: ID) {
  user(login: $login, id: $id) {
    ...UserRef
    chatColor
    chatSettings {
      isEmoteOnlyModeEnabled isFastSubsModeEnabled isSubscribersOnlyModeEnabled
      isUniqueChatModeEnabled slowModeDurationSeconds followersOnlyDurationMinutes
      requireVerifiedAccount chatDelayMs rules
    }
    channel {
      pinnedChatMessages {
        edges {
          node {
            id startsAt endsAt
            pinnedBy { id login displayName }
            pinnedMessage { id sentAt content { text } sender { id login displayName } }
          }
        }
      }
    }
  }
}
"""

CHANNEL_POINTS = USER_REF + """
query ChannelPoints($login: String, $id: ID) {
  user(login: $login, id: $id) {
    ...UserRef
    channel {
      communityPointsSettings {
        name isEnabled
        image { url }
        emoteVariants { id isUnlockable emote { id token } }
        customRewards {
          id title prompt cost isEnabled isPaused isInStock isUserInputRequired
          backgroundColor shouldRedemptionsSkipRequestQueue
          image { url }
          defaultImage { url }
          maxPerStreamSetting { isEnabled maxPerStream }
          maxPerUserPerStreamSetting { isEnabled maxPerUserPerStream }
          globalCooldownSetting { isEnabled globalCooldownSeconds }
        }
      }
    }
  }
}
"""

CHANNEL_EMOTES = USER_REF + BADGE + """
query ChannelEmotes($login: String, $id: ID) {
  user(login: $login, id: $id) {
    ...UserRef
    subscriptionProducts {
      id name tier displayName emoteSetID
      emotes { id token setID }
    }
    cheer {
      cheerGroups {
        nodes {
          id prefix
          tiers { bits color images { theme isAnimated dpiScale url } }
        }
      }
    }
    broadcastBadges { ...Badge }
  }
}
"""

CHANNEL_VIPS = USER_REF + """
query ChannelVips($login: String, $id: ID) {
  user(login: $login, id: $id) {
    ...UserRef
    vips(first: 100) { edges { grantedAt node { id login displayName } } }
  }
}
"""

CHANNEL_CHATTERS = USER_REF + """
query ChannelChatters($login: String, $id: ID) {
  user(login: $login, id: $id) {
    ...UserRef
    stream { id viewersCount }
    channel {
      chatters {
        count
        broadcasters { login }
        moderators { login }
        vips { login }
        staff { login }
        viewers { login }
      }
    }
  }
}
"""

VIEWER_CARD = USER_REF + BADGE + """
query ViewerCard($channelLogin: String!, $userLogin: String!) {
  channelViewer(channelLogin: $channelLogin, userLogin: $userLogin) {
    id
    earnedBadges { ...Badge }
  }
  user(login: $userLogin) {
    id login displayName description createdAt chatColor
    profileImageURL(width: 150)
    roles { isPartner isAffiliate isStaff }
    followers { totalCount }
    stream { id viewersCount }
  }
  channel: user(login: $channelLogin) { ...UserRef }
}
"""

STREAM_PLAYBACK_TOKEN = USER_REF + """
query StreamPlaybackToken($login: String!) {
  user(login: $login) { ...UserRef stream { id viewersCount } }
  streamPlaybackAccessToken(channelName: $login, params: {platform: "web", playerBackend: "mediaplayer", playerType: "site"}) {
    signature value
  }
}
"""

VIDEO_PLAYBACK_TOKEN = USER_REF + """
query VideoPlaybackToken($id: ID!) {
  video(id: $id) { id title lengthSeconds owner { ...UserRef } }
  videoPlaybackAccessToken(id: $id, params: {platform: "web", playerBackend: "mediaplayer", playerType: "site"}) {
    signature value
  }
}
"""

USER_ID_LOOKUP = """
query UserIdLookup($login: String, $id: ID) {
  user(login: $login, id: $id) { id login }
}
"""


# ---- directory ---------------------------------------------------------------------------

STREAMS = _STREAM_DEPS + """
query Streams($first: Int!, $after: Cursor, $options: StreamOptions) {
  streams(first: $first, after: $after, options: $options) {
    edges { cursor node { ...StreamCard } }
    pageInfo { hasNextPage }
  }
}
"""

GAMES = GAME_REF + GAME_CARD + """
query Games($first: Int!, $after: Cursor, $options: GameOptions) {
  games(first: $first, after: $after, options: $options) {
    edges { cursor node { ...GameCard } }
    pageInfo { hasNextPage }
  }
}
"""

GAME_DETAILS = GAME_REF + GAME_CARD + """
query GameDetails($name: String, $slug: String, $id: ID) {
  game(name: $name, slug: $slug, id: $id) {
    ...GameCard
    broadcastersCount description originalReleaseDate
    developers publishers
    logoURL coverURL
  }
}
"""

GAME_STREAMS = _STREAM_DEPS + """
query GameStreams($name: String, $slug: String, $id: ID, $first: Int!, $after: Cursor, $options: GameStreamOptions) {
  game(name: $name, slug: $slug, id: $id) {
    ...GameRef
    viewersCount
    streams(first: $first, after: $after, options: $options) {
      edges { cursor node { ...StreamCard } }
      pageInfo { hasNextPage }
    }
  }
}
"""

GAME_VIDEOS = _VIDEO_DEPS + """
query GameVideos($name: String, $slug: String, $id: ID, $first: Int!, $after: Cursor, $sort: VideoSort, $types: [BroadcastType!], $languages: [String!]) {
  game(name: $name, slug: $slug, id: $id) {
    ...GameRef
    videos(first: $first, after: $after, sort: $sort, types: $types, languages: $languages) {
      edges { cursor node { ...VideoCard } }
      pageInfo { hasNextPage }
    }
  }
}
"""

GAME_CLIPS = _CLIP_DEPS + """
query GameClips($name: String, $slug: String, $id: ID, $first: Int!, $after: Cursor, $criteria: GameClipsInput) {
  game(name: $name, slug: $slug, id: $id) {
    ...GameRef
    clips(first: $first, after: $after, criteria: $criteria) {
      edges { cursor node { ...ClipCard } }
      pageInfo { hasNextPage }
    }
  }
}
"""

TAGS_SEARCH = """
query TagsSearch($query: String!, $first: Int!) {
  searchFreeformTags(userQuery: $query, first: $first) {
    edges { node { tagName } }
  }
}
"""

GLOBAL_BADGES = BADGE + """
query GlobalBadges {
  badges { ...Badge }
}
"""


# ---- search ------------------------------------------------------------------------------

_SEARCH_USER = """
fragment SearchUser on User {
  ...UserRef
  description
  followers { totalCount }
  stream { id title viewersCount createdAt language game { ...GameRef } }
}
"""

SEARCH_ALL = _VIDEO_DEPS + _SEARCH_USER + """
query SearchAll($query: String!, $requestID: ID!, $channels: Int!, $games: Int!, $videos: Int!) {
  searchFor(userQuery: $query, platform: "web", requestID: $requestID, options: {
    targets: [
      {index: CHANNEL, limit: $channels},
      {index: GAME, limit: $games},
      {index: VOD, limit: $videos}
    ]
  }) {
    channels { totalMatches cursor edges { item { ... on User { ...SearchUser } } } }
    games { totalMatches cursor edges { item { ... on Game { ...GameRef viewersCount } } } }
    videos { totalMatches cursor edges { item { ... on Video { ...VideoCard } } } }
  }
}
"""

SEARCH_CHANNELS = USER_REF + GAME_REF + _SEARCH_USER + """
query SearchChannels($query: String!, $requestID: ID!, $first: Int!, $cursor: String) {
  searchFor(userQuery: $query, platform: "web", requestID: $requestID, options: {
    targets: [{index: CHANNEL, limit: $first, cursor: $cursor}]
  }) {
    channels { totalMatches cursor edges { item { ... on User { ...SearchUser } } } }
  }
}
"""

SEARCH_VIDEOS = _VIDEO_DEPS + """
query SearchVideos($query: String!, $requestID: ID!, $first: Int!, $cursor: String) {
  searchFor(userQuery: $query, platform: "web", requestID: $requestID, options: {
    targets: [{index: VOD, limit: $first, cursor: $cursor}]
  }) {
    videos { totalMatches cursor edges { item { ... on Video { ...VideoCard } } } }
  }
}
"""

SEARCH_GAMES = GAME_REF + GAME_CARD + """
query SearchGames($query: String!, $first: Int!, $after: Cursor) {
  searchCategories(query: $query, first: $first, after: $after) {
    edges { cursor node { ...GameCard } }
    pageInfo { hasNextPage }
  }
}
"""

SEARCH_SUGGEST = """
query SearchSuggest($query: String!, $requestID: ID!) {
  searchSuggestions(queryFragment: $query, requestID: $requestID) {
    edges {
      node {
        id text
        content {
          __typename
          ... on SearchSuggestionChannel {
            id login isLive isVerified
            profileImageURL(width: 50)
            user { displayName followers { totalCount } }
          }
          ... on SearchSuggestionCategory {
            id boxArtURL
            game { name displayName slug viewersCount }
          }
        }
      }
    }
  }
}
"""


# ---- videos / clips / teams ---------------------------------------------------------------

VIDEO_DETAILS = _VIDEO_DEPS + """
query VideoDetails($id: ID!) {
  video(id: $id) {
    ...VideoCard
    updatedAt recordedAt offsetSeconds
    seekPreviewsURL
    resourceRestriction { id type }
    owner { description followers { totalCount } }
    moments(first: 100, momentRequestType: VIDEO_CHAPTER_MARKERS) {
      edges {
        node {
          id description type positionMilliseconds durationMilliseconds
          thumbnailURL
          details { ... on GameChangeMomentDetails { game { ...GameRef } } }
        }
      }
    }
  }
}
"""

VIDEO_CHAT = """
query VideoChat($id: ID!, $offset: Int, $after: Cursor) {
  video(id: $id) {
    id lengthSeconds
    comments(contentOffsetSeconds: $offset, after: $after) {
      edges {
        cursor
        node {
          id contentOffsetSeconds createdAt
          commenter { id login displayName }
          message {
            userColor
            fragments { text emote { id emoteID } }
            userBadges { id setID version }
          }
        }
      }
      pageInfo { hasNextPage hasPreviousPage }
    }
  }
}
"""

CLIP_DETAILS = _CLIP_DEPS + """
query ClipDetails($slug: ID!) {
  clip(slug: $slug) {
    ...ClipCard
    embedURL
    broadcaster { description followers { totalCount } }
    video { id title lengthSeconds }
    videoQualities { quality frameRate sourceURL }
    playbackAccessToken(params: {platform: "web", playerType: "clips-embed"}) { signature value }
  }
}
"""

TEAM_DETAILS = USER_REF + GAME_REF + """
query TeamDetails($name: String!) {
  team(name: $name) {
    id name displayName description
    logoURL backgroundImageURL bannerURL
    members(first: 100) {
      totalCount
      edges {
        node {
          ...UserRef
          followers { totalCount }
          stream { id title viewersCount createdAt game { ...GameRef } }
        }
      }
    }
  }
}
"""
