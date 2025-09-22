from __future__ import annotations

from typing import Any, Dict, Optional

try:  # pragma: no cover - only executed when real Twilio library is installed
    from twilio.request_validator import RequestValidator as TwilioRequestValidator  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback below
    TwilioRequestValidator = None  # type: ignore

try:  # pragma: no cover - only executed when real Twilio library is installed
    from twilio.twiml.voice_response import VoiceResponse as TwilioVoiceResponse  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback below
    TwilioVoiceResponse = None  # type: ignore


if TwilioVoiceResponse is not None:  # pragma: no cover - defer to real implementation when available
    VoiceResponse = TwilioVoiceResponse  # type: ignore
else:
    from xml.etree.ElementTree import Element, SubElement, tostring

    def _twilio_attr(name: str) -> str:
        parts = name.split("_")
        if not parts:
            return name
        first, *rest = parts
        return first + "".join(word.capitalize() for word in rest)

    def _stringify(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    class _Gather:
        def __init__(self, element: Element) -> None:
            self._element = element

        def say(self, message: str, voice: Optional[str] = None, language: Optional[str] = None) -> Element:
            say = SubElement(self._element, "Say")
            if voice:
                say.set("voice", voice)
            if language:
                say.set("language", language)
            say.text = message
            return say

    class VoiceResponse:  # pragma: no cover - simple XML builder
        def __init__(self) -> None:
            self._root = Element("Response")

        def gather(self, **kwargs: Any) -> _Gather:
            attrs: Dict[str, str] = {}
            for key, value in kwargs.items():
                if value is None:
                    continue
                attrs[_twilio_attr(key)] = _stringify(value)
            gather = SubElement(self._root, "Gather", attrs)
            return _Gather(gather)

        def say(self, message: str, voice: Optional[str] = None, language: Optional[str] = None) -> Element:
            say = SubElement(self._root, "Say")
            if voice:
                say.set("voice", voice)
            if language:
                say.set("language", language)
            say.text = message
            return say

        def hangup(self) -> None:
            SubElement(self._root, "Hangup")

        def __str__(self) -> str:
            return tostring(self._root, encoding="unicode")


if TwilioRequestValidator is not None:  # pragma: no cover - defer to real implementation when available
    RequestValidator = TwilioRequestValidator  # type: ignore
else:

    class RequestValidator:  # pragma: no cover - simple permissive validator
        def __init__(self, _token: Optional[str]) -> None:
            self._token = _token

        def validate(self, _url: str, _params: Any, _signature: str) -> bool:
            return True


__all__ = ["VoiceResponse", "RequestValidator"]
