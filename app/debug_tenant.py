from fastapi import APIRouter, Query

from app.config import get_settings_for_to_number

router = APIRouter()


@router.get("/debug/which-practice")
def which_practice(to: str = Query(..., description="E.164 number e.g. +4420...")):
    settings = get_settings_for_to_number(to)
    return {
        "to": to,
        "profile": settings.profile,
        "practice_name": settings.practice.practice_name,
        "voice": settings.voice,
        "has_openings": bool(settings.practice.openings),
    }
