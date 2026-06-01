"""MusicKit mock wiring for frontend tests.

Builds a ``MusicKitApiMock`` (from ``musickit-api-mock-playwright``) and
attaches it to a Playwright page. The library covers the default
MusicKit JS surface — catalog/library/DRM/EME and the authorize flow —
so the test only configures resource data and per-endpoint overrides.

A thin ``page.route`` overlay handles ``/v1/catalog/<sf>/search`` because
the upstream library does not yet implement that endpoint. The overlay
is registered after ``intercept`` so it wins via Playwright's LIFO route
matching.

The silence audio used to back ``Song.from_file`` is generated once per
process in ``_silence_song()`` via PyAV (a transitive dep of
``musickit-api-mock``).
"""

import base64
import json
import tempfile
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from urllib.parse import urlparse

from musickit_api_mock import (
    Account,
    AccountResponseFailure,
    AccountResponseSuccess,
    Artwork,
    AuthorizeSuccess,
    LibraryPlaylist,
    LicenseResponseSuccess,
    LogoutResponseSuccess,
    LookupContext,
    MusicKitApiMock,
    PlayActivityResponseSuccess,
    Playlist,
    Song,
    SongMetadataFallback,
    Storefront,
    StorefrontResponseFailure,
    StorefrontResponseSuccess,
    WebPlaybackAsset,
    WebPlaybackResponse,
    WebPlaybackResponseServerError,
    WebPlaybackResponseSuccess,
    WebPlaybackSong,
    WidevineCertResponseSuccess,
)
from musickit_api_mock_playwright import intercept
from playwright.sync_api import Page, Route


# MusicKit namespaces its persisted auth in localStorage by the developer
# token's team id (the JWT ``iss`` claim).
_DEVELOPER_TEAM_ID = "test-team"


def make_developer_token(*, expired: bool = False) -> str:
    """Generate a JWT that MusicKit accepts structurally.

    MusicKit validates structure and exp claim locally.
    Signature is NOT validated client-side.
    """

    def _b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = _b64url(json.dumps({"alg": "ES256", "kid": "test"}).encode())
    now = int(time.time())
    exp = now - 86400 if expired else now + 86400
    payload = _b64url(
        json.dumps({"iss": _DEVELOPER_TEAM_ID, "iat": now, "exp": exp}).encode()
    )
    signature = _b64url(b"\x00" * 64)
    return f"{header}.{payload}.{signature}"


SAMPLE_CATALOG_SONGS: list[str] = [f"song{i}" for i in range(1, 11)]
DEFAULT_SEARCH_PLAYLIST_IDS: list[str] = ["pl.test"]
DEFAULT_LIBRARY_PLAYLIST_IDS: list[str] = ["p.lib1", "p.lib2"]


_silence_song_cache: Song | None = None


def _build_silence_audio(out_path: Path, *, duration_sec: float = 2.0) -> None:
    import av
    from av.audio.frame import AudioFrame

    sample_rate = 44100
    container = av.open(str(out_path), "w", format="mp4")
    audio = container.add_stream("aac", rate=sample_rate)
    audio.layout = "mono"
    samples_per_frame = 1024
    total = int(duration_sec * sample_rate)
    silence_full = bytes(samples_per_frame * 4)
    pts = 0
    while pts < total:
        n = min(samples_per_frame, total - pts)
        frame = AudioFrame(format="fltp", layout="mono", samples=n)
        frame.sample_rate = sample_rate
        frame.planes[0].update(silence_full if n == samples_per_frame else bytes(n * 4))
        frame.pts = pts
        for pkt in audio.encode(frame):
            container.mux(pkt)
        pts += n
    for pkt in audio.encode(None):
        container.mux(pkt)
    container.close()


def _silence_song() -> Song:
    global _silence_song_cache
    if _silence_song_cache is None:
        # Generated once per worker process; small (~5 KB) AAC m4a.
        path = Path(tempfile.gettempdir()) / "ateruta_musickit_silence.m4a"
        if not path.exists():
            _build_silence_audio(path)
        fallback = SongMetadataFallback(
            artwork=Artwork(
                url="https://example.test/artwork.jpg", width=64, height=64
            ),
            has_lyrics=False,
            audio_locale="en-US",
            audio_traits=["lossless"],
            has_time_synced_lyrics=False,
            is_apple_digital_master=False,
            is_mastered_for_itunes=False,
            is_vocal_attenuation_allowed=False,
            url="https://music.apple.com/us/song/placeholder",
            title="Silence",
            artist="Test Artist",
            album="Test Album",
            genres=["Test"],
            release_date="2020-01-01",
            track_number=1,
            disc_number=1,
        )
        _silence_song_cache = Song.from_file(str(path), fallback)
    return _silence_song_cache


def _make_song(song_id: str) -> Song:
    base = _silence_song()
    n = song_id.removeprefix("song") or song_id
    return Song(
        title=f"Song {n}",
        artist=f"Artist {n}",
        album=base.album,
        duration_ms=base.duration_ms,
        artwork=base.artwork,
        genres=list(base.genres),
        has_lyrics=base.has_lyrics,
        audio_locale=base.audio_locale,
        audio_traits=list(base.audio_traits),
        has_time_synced_lyrics=base.has_time_synced_lyrics,
        is_apple_digital_master=base.is_apple_digital_master,
        is_mastered_for_itunes=base.is_mastered_for_itunes,
        is_vocal_attenuation_allowed=base.is_vocal_attenuation_allowed,
        url=f"https://music.apple.com/us/song/{song_id}",
        hls_layout=base.hls_layout,
        hls_segment=base.hls_segment,
        preview_audio=base.preview_audio,
        bitrate=base.bitrate,
        sample_rate=base.sample_rate,
        file_size=base.file_size,
        release_date=base.release_date,
        track_number=base.track_number,
        disc_number=base.disc_number,
    )


def _make_playlist(playlist_id: str, track_ids: list[str]) -> Playlist:
    return Playlist(
        name=f"Playlist {playlist_id}",
        playlist_type="editorial",
        curator_name="Apple Music",
        has_collaboration=False,
        is_chart=False,
        audio_traits=[],
        supports_sing=False,
        url=f"https://music.apple.com/us/playlist/x/{playlist_id}",
        artwork=Artwork(url="https://example.test/playlist.jpg", width=200, height=200),
        track_ids=track_ids,
    )


def _make_library_playlist(playlist_id: str) -> LibraryPlaylist:
    name = "Test Playlist" if playlist_id == "p.lib1" else f"Library {playlist_id}"
    return LibraryPlaylist(
        name=name,
        can_delete=True,
        can_edit=True,
        is_public=False,
        has_catalog=False,
        has_collaboration=False,
        track_ids=[],
        artwork=Artwork(url="https://example.test/library.jpg", width=200, height=200),
    )


def _build_web_playback(
    song_ids: Iterable[str], *, error: bool
) -> dict[str, WebPlaybackResponse]:
    if error:
        return {song_id: WebPlaybackResponseServerError() for song_id in song_ids}
    return {
        song_id: WebPlaybackResponseSuccess(
            song_list=[
                WebPlaybackSong(
                    song_id=song_id,
                    hls_key_cert_url="https://s.mzstatic.com/skdtool_2021_certbundle.bin",
                    hls_key_server_url="https://play.itunes.apple.com/WebObjects/MZPlay.woa/wa/acquireWebPlaybackLicense",
                    widevine_cert_url="https://play.itunes.apple.com/WebObjects/MZPlay.woa/wa/widevineCert",
                    assets=[
                        WebPlaybackAsset(
                            flavor="30:ctrp256",
                            url=f"https://aod-ssl.itunes.apple.com/itunes-assets/{song_id}/index.m3u8",
                        )
                    ],
                )
            ]
        )
        for song_id in song_ids
    }


def _build_search_response(playlist_ids: list[str]) -> dict[str, object]:
    return {
        "results": {
            "playlists": {
                "data": [
                    {
                        "id": pid,
                        "type": "playlists",
                        "href": f"/v1/catalog/us/playlists/{pid}",
                        "attributes": {
                            "name": f"Playlist {pid}",
                            "artwork": {
                                "url": "https://example.test/playlist.jpg",
                                "width": 200,
                                "height": 200,
                            },
                            "playlistType": "editorial",
                            "url": f"https://music.apple.com/us/playlist/x/{pid}",
                        },
                    }
                    for pid in playlist_ids
                ],
            },
        },
    }


def _build_library_playlists_response(playlist_ids: list[str]) -> dict[str, object]:
    return {
        "data": [
            {
                "id": pid,
                "type": "library-playlists",
                "href": f"/v1/me/library/playlists/{pid}",
                "attributes": {
                    "name": "Test Playlist" if pid == "p.lib1" else f"Library {pid}",
                    "artwork": {
                        "url": "https://example.test/library.jpg",
                        "width": 200,
                        "height": 200,
                    },
                },
            }
            for pid in playlist_ids
        ],
    }


_CORS_PREFLIGHT_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "*",
}


def _register_search_override(
    page: Page,
    *,
    search_error: bool,
    playlist_ids: list[str],
) -> None:
    def handler(route: Route) -> None:
        if route.request.method == "OPTIONS":
            route.fulfill(status=204, headers=_CORS_PREFLIGHT_HEADERS)
            return
        if search_error:
            route.fulfill(
                status=500,
                body="Search error",
                headers={"Access-Control-Allow-Origin": "*"},
            )
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_build_search_response(playlist_ids)),
            headers={"Access-Control-Allow-Origin": "*"},
        )

    page.route("**/api.music.apple.com/v1/catalog/*/search*", handler)


def _register_library_playlists_override(
    page: Page,
    *,
    library_ids: list[str],
) -> None:
    def handler(route: Route) -> None:
        if urlparse(route.request.url).path != "/v1/me/library/playlists":
            route.fallback()
            return
        if route.request.method == "OPTIONS":
            route.fulfill(status=204, headers=_CORS_PREFLIGHT_HEADERS)
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_build_library_playlists_response(library_ids)),
            headers={"Access-Control-Allow-Origin": "*"},
        )

    page.route("**/api.music.apple.com/v1/me/library/playlists*", handler)


def _register_playlist_tracks_failure(page: Page) -> None:
    def handler(route: Route) -> None:
        if route.request.method == "OPTIONS":
            route.fulfill(status=204, headers=_CORS_PREFLIGHT_HEADERS)
            return
        route.fulfill(
            status=500,
            body="Network error",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    page.route("**/api.music.apple.com/v1/catalog/*/playlists/*/tracks*", handler)


_MUSICKIT_JS_GLOB = "**/musickit/v3/musickit.js"
_musickit_js_cache: dict[str, bytes] = {}
_MUSICKIT_SCRIPT_HOST = "js-cdn.music.apple.com"
_MUSICKIT_NETWORK_HOSTS = frozenset(
    {
        "api.music.apple.com",
        "play.itunes.apple.com",
        "aod-ssl.itunes.apple.com",
        "s.mzstatic.com",
    }
)


def _serve_musickit_js(page: Page) -> None:
    """Serve the real MusicKit JS so it runs against the mock.

    Fetches the upstream script once per process and replays it on every
    request, rather than stubbing it out. ``intercept`` injects the in-page
    shim that replaces only the browser integrations (EME, Media Source,
    authorize popup), so the genuine library drives playback against the
    mocked Apple Music API.
    """

    def handler(route: Route) -> None:
        if "body" not in _musickit_js_cache:
            _musickit_js_cache["body"] = route.fetch().body()
        route.fulfill(
            status=200,
            content_type="application/javascript",
            body=_musickit_js_cache["body"],
        )

    page.route(_MUSICKIT_JS_GLOB, handler)


def _is_musickit_js_request(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.hostname or ""
    ).lower() == _MUSICKIT_SCRIPT_HOST and parsed.path.endswith("/musickit.js")


def _is_musickit_network_request(url: str) -> bool:
    if _is_musickit_js_request(url):
        return False
    host = (urlparse(url).hostname or "").lower()
    return host in _MUSICKIT_NETWORK_HOSTS


def _block_unmocked_musickit_requests(page: Page) -> None:
    def handler(route: Route) -> None:
        if _is_musickit_network_request(route.request.url):
            route.abort()
            return
        route.fallback()

    page.route("**/*", handler)


def configure_musickit_api_mock(
    page: Page,
    *,
    authorized: bool = False,
    songs: Iterable[str] | None = None,
    library_playlist_ids: Iterable[str] | None = None,
    empty_playlist_ids: Iterable[str] | None = None,
    search_playlist_ids: Iterable[str] | None = None,
    search_error: bool = False,
    playlist_tracks_error: bool = False,
    playback_error: bool = False,
) -> MusicKitApiMock:
    """Wire the MusicKit mock onto a Playwright page.

    Call BEFORE ``page.goto`` — both the library shim and the search route
    overlay rely on ``addInitScript`` / ``page.route``, which persist
    through navigation.
    """
    song_ids = list(songs) if songs is not None else SAMPLE_CATALOG_SONGS[:2]
    library_ids = (
        list(library_playlist_ids)
        if library_playlist_ids is not None
        else DEFAULT_LIBRARY_PLAYLIST_IDS
    )
    search_ids = (
        list(search_playlist_ids)
        if search_playlist_ids is not None
        else DEFAULT_SEARCH_PLAYLIST_IDS
    )
    empty_ids = set(empty_playlist_ids or ())

    mock = MusicKitApiMock()
    mock.data.songs = {sid: _make_song(sid) for sid in song_ids}

    def resolve_playlist(ctx: LookupContext) -> Playlist | None:
        if ctx.id in empty_ids:
            return _make_playlist(ctx.id, track_ids=[])
        return _make_playlist(ctx.id, track_ids=list(song_ids))

    playlist_callable: Callable[[LookupContext], Playlist | None] = resolve_playlist
    mock.data.playlists = playlist_callable

    if authorized:
        mock.data.library_playlists = {
            pid: _make_library_playlist(pid) for pid in library_ids
        }
        mock.endpoints.storefront = StorefrontResponseSuccess(
            storefront=Storefront(
                id="us",
                name="United States",
                default_language_tag="en-US",
                supported_language_tags=["en-US"],
                explicit_content_policy="allowed",
            )
        )
        mock.endpoints.account = AccountResponseSuccess(
            account=Account(subscription_active=True, subscription_storefront="us")
        )
    else:
        mock.endpoints.storefront = StorefrontResponseFailure()
        mock.endpoints.account = AccountResponseFailure()

    mock.endpoints.web_playback = _build_web_playback(song_ids, error=playback_error)
    mock.endpoints.widevine_cert = WidevineCertResponseSuccess(cert=b"")
    mock.endpoints.license_catalog_song = LicenseResponseSuccess(license=b"")
    mock.endpoints.play_activity = PlayActivityResponseSuccess()
    mock.endpoints.webplayer_logout = LogoutResponseSuccess()
    mock.browser.eme_flavor = "com.widevine.alpha"
    # Unconditional: the unauthorized page still needs this for the
    # authorize() click path.
    mock.browser.authorize_response = AuthorizeSuccess(
        user_token="fake-music-user-token", cid="cid", restricted=0
    )

    if authorized:
        # MusicKit reports isAuthorized at configure time from a media-user-token
        # it persists in localStorage; seeding it stands in for a prior session.
        page.add_init_script(
            f"""(() => {{
                const ns = "music.{_DEVELOPER_TEAM_ID}";
                localStorage.setItem(ns + ".media-user-token", "fake-music-user-token");
                localStorage.setItem(ns + ".itua", "us");
                localStorage.setItem(ns + ".pldfltcid", "cid");
                localStorage.setItem(ns + ".itre", "0");
            }})();"""
        )

    _serve_musickit_js(page)
    _block_unmocked_musickit_requests(page)
    intercept(mock, page)
    _register_search_override(
        page,
        search_error=search_error,
        playlist_ids=search_ids,
    )
    _register_library_playlists_override(page, library_ids=library_ids)
    if playlist_tracks_error:
        _register_playlist_tracks_failure(page)
    return mock
