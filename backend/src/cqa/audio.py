"""Bounded audio ingestion; signed URLs are never stored in provider requests or logs."""

import asyncio
import hashlib
import io
import ipaddress
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx
from mutagen import File as MutagenFile

MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_AUDIO_SECONDS = 900


class AudioError(ValueError):
    pass


@dataclass(frozen=True)
class AudioAsset:
    content: bytes
    format: str
    duration: float
    sha256: str


def inspect_audio(content: bytes) -> AudioAsset:
    if not content or len(content) > MAX_AUDIO_BYTES:
        raise AudioError("Audio must be nonempty and at most 25 MiB")
    try:
        audio = MutagenFile(io.BytesIO(content))
        duration = float(audio.info.length) if audio is not None else 0
        name = type(audio).__name__
    except Exception as exc:
        raise AudioError("Cannot decode audio metadata") from exc
    formats = {
        "MP3": "mp3",
        "WAVE": "wav",
        "FLAC": "flac",
        "MP4": "m4a",
        "OggOpus": "ogg",
        "OggVorbis": "ogg",
    }
    if name not in formats or not 0 < duration <= MAX_AUDIO_SECONDS:
        raise AudioError("Unsupported audio format or duration outside 0–900 seconds")
    return AudioAsset(content, formats[name], duration, hashlib.sha256(content).hexdigest())


class AudioSourceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in ("audio", "source") and attributes.get("src"):
            self.sources.append(attributes["src"])


async def public_address(host: str) -> str:
    """Resolve once, validate every answer, then pin the connection to an approved IP."""
    try:
        addresses = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM), 10
        )
    except (OSError, TimeoutError) as exc:
        raise AudioError("Audio host could not be resolved") from exc
    ips = {item[4][0] for item in addresses}
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise AudioError("Audio host resolved to a non-public address")
    return sorted(ips, key=lambda ip: (":" in ip, ip))[0]


async def download_audio(
    url: str, allowed_hosts: tuple[str, ...], transport: httpx.AsyncBaseTransport | None = None
) -> AudioAsset:
    """Only trusted HTTPS media/player hosts, checked again after each redirect."""
    async with httpx.AsyncClient(
        timeout=45, follow_redirects=False, transport=transport, trust_env=False
    ) as client:
        for _ in range(6):
            try:
                parsed = urlparse(url)
                port = parsed.port
            except ValueError as exc:
                raise AudioError("Invalid audio URL") from exc
            if (
                parsed.scheme != "https"
                or parsed.hostname not in allowed_hosts
                or parsed.username
                or parsed.password
                or port not in (None, 443)
            ):
                raise AudioError("Audio URL host is not allowed")
            try:
                target = httpx.URL(url)
                if transport is None:
                    target = target.copy_with(host=await public_address(parsed.hostname))
                async with client.stream(
                    "GET",
                    target,
                    headers={"Host": parsed.hostname, "Accept-Encoding": "identity"},
                    extensions={"sni_hostname": parsed.hostname},
                ) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            raise AudioError("Audio redirect has no destination")
                        url = urljoin(url, location)
                        continue
                    response.raise_for_status()
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise AudioError("Compressed audio responses are not accepted")
                    html = "text/html" in response.headers.get("content-type", "").lower()
                    limit = 65536 if html else MAX_AUDIO_BYTES
                    content = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        content.extend(chunk)
                        if len(content) > limit:
                            raise AudioError("Audio or player response exceeds size limit")
                if html:
                    parser = AudioSourceParser()
                    parser.feed(content.decode("utf-8", errors="replace"))
                    if len(set(parser.sources)) != 1:
                        raise AudioError("Player must contain one unambiguous audio source")
                    url = urljoin(url, parser.sources[0])
                    continue
                return inspect_audio(bytes(content))
            except httpx.HTTPError as exc:
                raise AudioError("Audio source could not be downloaded") from exc
    raise AudioError("Too many audio redirects or nested players")
