import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import or_, text
from sqlalchemy.orm import Session, joinedload

from .database import BASE_DIR, Base, SessionLocal, engine, get_db
from .models import (
    Announcement,
    Cage,
    LoginMemory,
    Rack,
    Room,
    SyncOperation,
    UsageRecord,
    User,
)
from .security import hash_password, verify_password
from .seed import seed_data


app = FastAPI(title="Mice Manage MVP")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

STATUS_OPTIONS = ["繁殖", "实验"]
ACTION_OPTIONS = ["查看", "取用", "归还", "补笼", "换笼", "清笼", "备注"]


class SyncItem(BaseModel):
    op_id: str
    action_type: str
    cage_code: str
    operator_name: str
    payload: dict[str, Any]
    client_created_at: str | None = None


class SyncRequest(BaseModel):
    items: list[SyncItem]


def summarize_sync_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "results": results,
        "success_count": sum(1 for item in results if item["status"] == "success"),
        "failed_count": sum(
            1 for item in results if item["status"] not in {"success", "duplicate"}
        ),
        "duplicate_count": sum(
            1 for item in results if item["status"] == "duplicate"
        ),
    }


def bootstrap() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    db = SessionLocal()
    try:
        normalize_users(db)
        seed_data(db)
        normalize_cage_genotypes(db)
        normalize_cage_statuses(db)
    finally:
        db.close()


def ensure_schema() -> None:
    with engine.begin() as conn:
        cage_columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(cages)")).fetchall()
        }
        if "male_genotype" not in cage_columns:
            conn.execute(text("ALTER TABLE cages ADD COLUMN male_genotype VARCHAR(100)"))
        if "female_genotype" not in cage_columns:
            conn.execute(text("ALTER TABLE cages ADD COLUMN female_genotype VARCHAR(100)"))
        if "cage_tag_image" not in cage_columns:
            conn.execute(text("ALTER TABLE cages ADD COLUMN cage_tag_image VARCHAR(255)"))
        conn.execute(
            text(
                "UPDATE cages SET male_genotype = strain "
                "WHERE (male_genotype IS NULL OR male_genotype = '') "
                "AND strain IS NOT NULL AND strain != ''"
            )
        )
        conn.execute(
            text(
                "UPDATE cages SET female_genotype = strain "
                "WHERE (female_genotype IS NULL OR female_genotype = '') "
                "AND strain IS NOT NULL AND strain != ''"
            )
        )
        user_columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()
        }
        if "password_hash" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255)"))


def normalize_users(db: Session) -> None:
    changed = False

    member_users = db.query(User).filter(User.role == "member").all()
    for user in member_users:
        user.role = "owner"
        changed = True

    old_admin = db.query(User).filter(User.name.in_(["王老师", "鐜嬭€佸笀"])).first()
    target_admin = db.query(User).filter(User.name.in_(["任老师", "浠昏€佸笀"])).first()
    if old_admin and not target_admin:
        old_admin.name = "任老师"
        changed = True
    elif old_admin and target_admin and old_admin.id != target_admin.id:
        for cage in db.query(Cage).filter(Cage.owner_user_id == old_admin.id).all():
            cage.owner_user_id = target_admin.id
        for record in db.query(UsageRecord).filter(UsageRecord.user_id == old_admin.id).all():
            record.user_id = target_admin.id
        db.delete(old_admin)
        changed = True

    target_admin = db.query(User).filter(User.name == "任老师", User.role == "admin").first()
    if target_admin:
        target_password_hash = hash_password("Renlab123")
        if not target_admin.password_hash or not verify_password("Renlab123", target_admin.password_hash):
            target_admin.password_hash = target_password_hash
            changed = True

    if changed:
        db.commit()


def normalize_cage_statuses(db: Session) -> None:
    changed = False
    for cage in db.query(Cage).all():
        current = str(cage.status or "").strip()
        normalized = "实验" if current in {"实验", "瀹為獙"} else "繁殖"
        if cage.status != normalized:
            cage.status = normalized
            changed = True
    if changed:
        db.commit()


def normalize_cage_genotypes(db: Session) -> None:
    changed = False
    for cage in db.query(Cage).all():
        male, female = resolve_genotypes(
            cage.male_genotype,
            cage.female_genotype,
            cage.strain,
        )
        derived_strain = derive_legacy_strain(male, female, cage.strain)
        if cage.male_genotype != (male or None):
            cage.male_genotype = male or None
            changed = True
        if cage.female_genotype != (female or None):
            cage.female_genotype = female or None
            changed = True
        if cage.strain != derived_strain:
            cage.strain = derived_strain
            changed = True
    if changed:
        db.commit()


@app.on_event("startup")
def on_startup() -> None:
    bootstrap()


@app.get("/manifest.json", include_in_schema=False)
def web_manifest() -> FileResponse:
    return FileResponse(
        BASE_DIR / "static" / "manifest.json",
        media_type="application/manifest+json",
    )


@app.get("/sw.js", include_in_schema=False)
def service_worker() -> FileResponse:
    return FileResponse(
        BASE_DIR / "static" / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


def get_current_user(request: Request, db: Session) -> User | None:
    user_id = request.cookies.get("user_id")
    if not user_id:
        return None
    try:
        return db.get(User, int(user_id))
    except ValueError:
        return None


def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "").strip()
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def get_last_login_user(request: Request, db: Session) -> User | None:
    login_memory = (
        db.query(LoginMemory)
        .options(joinedload(LoginMemory.user))
        .filter(LoginMemory.ip_address == get_client_ip(request))
        .first()
    )
    if not login_memory:
        return None
    user = login_memory.user
    if not user or user.name == "已删除用户":
        return None
    return user


def require_user(request: Request, db: Session) -> User:
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, detail="璇峰厛鐧诲綍")
    return user


def require_admin(request: Request, db: Session) -> User:
    user = require_user(request, db)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="鍙湁绠＄悊鍛樺彲浠ヨ闂椤甸潰")
    return user


def can_edit_cage(user: User, cage: Cage) -> bool:
    return user.role == "admin" or user.id == cage.owner_user_id


def is_experiment_cage(cage: Cage) -> bool:
    return str(cage.status or "").strip() in {"实验", "瀹為獙"}


def build_context(request: Request, db: Session, extra: dict | None = None) -> dict:
    context = {
        "request": request,
        "current_user": get_current_user(request, db),
        "now": datetime.now(),
    }
    if extra:
        context.update(extra)
    return context


def load_announcements(db: Session) -> list[Announcement]:
    return (
        db.query(Announcement)
        .options(joinedload(Announcement.user))
        .order_by(Announcement.created_at.desc())
        .all()
    )


def parse_optional_date(value: str) -> date | None:
    value = value.strip()
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def add_months(source_date: date, months: int) -> date:
    month_index = source_date.month - 1 + months
    year = source_date.year + month_index // 12
    month = month_index % 12 + 1
    month_lengths = [
        31,
        29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28,
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ]
    day = min(source_date.day, month_lengths[month - 1])
    return date(year, month, day)


def split_search_terms(value: str) -> list[str]:
    normalized = value.replace("，", " ").replace(",", " ")
    return [term.strip() for term in normalized.split() if term.strip()]


def birth_upload_dir() -> Path:
    return BASE_DIR / "static" / "uploads" / "birth_records"


def cage_tag_upload_dir() -> Path:
    return BASE_DIR / "static" / "uploads" / "cage_tags"


def save_birth_image(upload: UploadFile | None) -> str | None:
    if not upload or not upload.filename:
        return None

    suffix = Path(upload.filename).suffix or ".jpg"
    filename = f"{uuid4().hex}{suffix}"
    target_dir = birth_upload_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename
    content = upload.file.read()
    if not content:
        return None
    target_path.write_bytes(content)
    return f"/static/uploads/birth_records/{filename}"


def save_cage_tag_image(upload: UploadFile | None) -> str | None:
    if not upload or not upload.filename:
        return None

    suffix = Path(upload.filename).suffix or ".jpg"
    filename = f"{uuid4().hex}{suffix}"
    target_dir = cage_tag_upload_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename
    content = upload.file.read()
    if not content:
        return None
    target_path.write_bytes(content)
    return f"/static/uploads/cage_tags/{filename}"


def save_birth_images(uploads: list[UploadFile] | None) -> list[str]:
    saved_paths: list[str] = []
    for upload in uploads or []:
        image_path = save_birth_image(upload)
        if image_path:
            saved_paths.append(image_path)
    return saved_paths


def remove_birth_image(image_path: str | None) -> None:
    if not image_path:
        return
    if not image_path.startswith("/static/uploads/birth_records/"):
        return
    file_path = BASE_DIR / image_path.lstrip("/")
    if file_path.exists():
        file_path.unlink()


def remove_cage_tag_image(image_path: str | None) -> None:
    if not image_path:
        return
    if not image_path.startswith("/static/uploads/cage_tags/"):
        return
    file_path = BASE_DIR / image_path.lstrip("/")
    if file_path.exists():
        file_path.unlink()


def remove_birth_images(image_paths: list[str]) -> None:
    for image_path in image_paths:
        remove_birth_image(image_path)


def build_birth_summary(cage: Cage) -> dict[str, Any] | None:
    for record in cage.usage_records:
        if record.action != "鏂扮敓鐧昏":
            continue
        summary: dict[str, Any] = {
            "created_at": record.created_at,
            "note": record.note,
            "birth_date": "-",
            "count": "0",
            "codes": "-",
        }
        if record.purpose:
            parts = [part.strip() for part in record.purpose.split("|")]
            for part in parts:
                if ":" not in part:
                    continue
                key, value = part.split(":", 1)
                normalized_key = key.strip()
                normalized_value = value.strip()
                if normalized_key in {"鍑虹敓鏃ユ湡", "birth_date"}:
                    summary["birth_date"] = normalized_value or "-"
                elif normalized_key in {"鏁伴噺", "count"}:
                    summary["count"] = normalized_value or "0"
                elif normalized_key in {"缂栧彿", "codes"}:
                    summary["codes"] = normalized_value or "-"
        return summary
    return None


def parse_birth_record(record: UsageRecord) -> dict[str, Any] | None:
    purpose_text = record.purpose or ""
    is_birth_record = (
        "birth_date=" in purpose_text
        or "count=" in purpose_text
        or "codes=" in purpose_text
        or record.action in {"鏂扮敓鐧昏", "閺傛壆鏁撻惂鏄忣唶"}
    )
    if not is_birth_record:
        return None

    parsed = {
        "id": record.id,
        "created_at": record.created_at,
        "operator": record.user.name if record.user else "",
        "birth_date": "-",
        "count": 0,
        "codes": "-",
        "processing": "-",
        "pcr_image": "",
        "pcr_images": [],
        "note": record.note or "",
    }
    if not record.purpose:
        return parsed

    parts = [part.strip() for part in record.purpose.split("|")]
    for part in parts:
        if "=" in part:
            key, value = part.split("=", 1)
        elif ":" in part:
            key, value = part.split(":", 1)
        else:
            continue
        normalized_key = key.strip()
        normalized_value = value.strip()
        if normalized_key in {"鍑虹敓鏃ユ湡", "閸戣櫣鏁撻弮銉︽埂", "birth_date"}:
            parsed["birth_date"] = normalized_value or "-"
        elif normalized_key in {"数量", "count"}:
            try:
                parsed["count"] = max(int(normalized_value), 0)
            except ValueError:
                parsed["count"] = 0
        elif normalized_key in {"编号", "codes"}:
            parsed["codes"] = normalized_value or "-"
        elif normalized_key in {"处理", "processing"}:
            parsed["processing"] = normalized_value or "-"
        elif normalized_key in {"pcr_image", "image"}:
            parsed["pcr_image"] = normalized_value
            parsed["pcr_images"] = [item for item in normalized_value.split(",") if item]
        elif normalized_key in {"pcr_images", "images"}:
            parsed["pcr_images"] = [item.strip() for item in normalized_value.split(",") if item.strip()]
            parsed["pcr_image"] = parsed["pcr_images"][0] if parsed["pcr_images"] else ""
    if not parsed["pcr_images"] and parsed["pcr_image"]:
        parsed["pcr_images"] = [parsed["pcr_image"]]
    return parsed


def build_birth_records(cage: Cage) -> list[dict[str, Any]]:
    return [parsed for record in cage.usage_records if (parsed := parse_birth_record(record))]


def build_birth_summary(cage: Cage) -> dict[str, Any] | None:
    records = build_birth_records(cage)
    return records[0] if records else None


def split_parent_codes(value: str | None) -> list[str]:
    text = str(value or "").replace("\r", "\n")
    parts = [item.strip() for item in text.split("\n") if item.strip()]
    return parts or [""]


def join_parent_codes(values: list[str] | None) -> str | None:
    if not values:
        return None
    cleaned = [str(item).strip() for item in values if str(item).strip()]
    return "\n".join(cleaned) if cleaned else None


def normalize_genotype(value: Any) -> str:
    return str(value or "").strip()


def resolve_genotypes(
    male_genotype: Any = "",
    female_genotype: Any = "",
    legacy_strain: Any = "",
) -> tuple[str, str]:
    male = normalize_genotype(male_genotype)
    female = normalize_genotype(female_genotype)
    legacy = normalize_genotype(legacy_strain)
    if not male and not female and legacy:
        return legacy, legacy
    return male, female


def derive_legacy_strain(
    male_genotype: Any = "",
    female_genotype: Any = "",
    legacy_strain: Any = "",
) -> str:
    male, female = resolve_genotypes(male_genotype, female_genotype, legacy_strain)
    if male and female:
        return male if male == female else f"父:{male} / 母:{female}"
    return male or female or normalize_genotype(legacy_strain)


def sanitize_record_action(value: str | None) -> str:
    text = str(value or "").strip()
    replacements = {
        "??": "更新",
        "鏇存柊": "更新",
        "????": "新生登记",
        "鏂扮敓鐧昏": "新生登记",
        "鏂扮敓鐧昏".replace("", "\ue187"): "新生登记",
        "鏂板": "新增",
        "鏂板".replace("", "\ue583"): "新增",
        "澶囨敞": "备注",
    }
    return replacements.get(text, text or "-")


def sanitize_record_purpose(record: UsageRecord) -> str:
    parsed_birth = parse_birth_record(record)
    if parsed_birth:
        parts = [
            f"出生日期：{parsed_birth['birth_date'] or '-'}",
            f"数量：{parsed_birth['count'] or 0}",
            f"编号：{parsed_birth['codes'] or '-'}",
            f"处理：{parsed_birth['processing'] or '-'}",
        ]
        return " | ".join(parts)

    text = str(record.purpose or "").strip()
    replacements = {
        "????": "新增笼位",
        "??????": "更新笼位信息",
        "鏇存柊绗间綅淇℃伅": "更新笼位信息",
        "绂荤嚎鍚屾鏂板绗间綅": "离线同步新增笼位",
        "绂荤嚎鍚屾鏂板绗间綅".replace("", "\ue11e").replace("", "\ue583"): "离线同步新增笼位",
        "绂荤嚎鍚屾鏇存柊绗间綅瀛楁": "离线同步更新笼位字段",
    }
    return replacements.get(text, text or "-")


def sanitize_record_note(record: UsageRecord) -> str:
    text = str(record.note or "").strip()
    parsed_birth = parse_birth_record(record)
    if parsed_birth:
        return text or "-"

    if text.startswith("???? "):
        cage_code = text.replace("???? ", "", 1).strip()
        return f"新增笼位 {cage_code}" if cage_code else "新增笼位"
    if text.startswith("鏂板绗间綅 ") or text.startswith("鏂板绗间綅 ".replace("", "\ue583")):
        cage_code = text.replace("鏂板绗间綅 ", "", 1).replace("鏂板绗间綅 ".replace("", "\ue583"), "", 1).strip()
        return f"新增笼位 {cage_code}" if cage_code else "新增笼位"
    if text.startswith("??? ") and text.endswith(" ?????"):
        cage_code = text.replace("??? ", "", 1).replace(" ?????", "").strip()
        return f"更新笼位 {cage_code} 信息" if cage_code else "更新笼位信息"
    if text.startswith("鏇存柊绗间綅 ") and text.endswith(" 淇℃伅"):
        cage_code = text.replace("鏇存柊绗间綅 ", "", 1).replace(" 淇℃伅", "").strip()
        return f"更新笼位 {cage_code} 信息" if cage_code else "更新笼位信息"
    if text == "绂荤嚎鍚屾鏇存柊绗间綅淇℃伅":
        return "离线同步更新笼位信息"
    return text or "-"


def needs_generation_alert(cage: Cage, today: date) -> bool:
    if is_experiment_cage(cage):
        return False
    setup_date_alert = bool(cage.setup_date and today >= add_months(cage.setup_date, 5))
    birth_dates: list[date] = []
    for birth_record in build_birth_records(cage):
        birth_date_text = str(birth_record["birth_date"]).strip()
        if not birth_date_text or birth_date_text == "-":
            continue
        try:
            birth_date_value = parse_optional_date(birth_date_text)
        except ValueError:
            continue
        birth_dates.append(birth_date_value)

    birth_dates.sort()
    overall_gap_alert = (
        len(birth_dates) >= 2 and (birth_dates[-1] - birth_dates[0]).days > 100
    )
    return setup_date_alert or overall_gap_alert


def needs_overcrowding_alert(cage: Cage, today: date) -> bool:
    if is_experiment_cage(cage):
        return False
    for birth_record in build_birth_records(cage):
        birth_date_text = str(birth_record["birth_date"]).strip()
        if not birth_date_text or birth_date_text == "-":
            continue
        try:
            birth_date_value = parse_optional_date(birth_date_text)
        except ValueError:
            continue
        if (today - birth_date_value).days > 21:
            return True
    return False


def needs_infertility_alert(cage: Cage, today: date) -> bool:
    if is_experiment_cage(cage):
        return False
    if not cage.setup_date:
        return False
    birth_records = build_birth_records(cage)
    if not birth_records:
        return today >= add_months(cage.setup_date, 2)

    latest_birth_record = birth_records[0]
    birth_date_text = str(latest_birth_record["birth_date"]).strip()
    if not birth_date_text or birth_date_text == "-":
        return False
    try:
        birth_date_value = parse_optional_date(birth_date_text)
    except ValueError:
        return False
    return (today - birth_date_value).days > 40


def serialize_birth_purpose(
    birth_date_value: str,
    count: int,
    codes: str,
    processing: str,
    pcr_image: str = "",
    pcr_images: list[str] | None = None,
) -> str:
    normalized_images = pcr_images if pcr_images is not None else ([pcr_image] if pcr_image else [])
    return " | ".join(
        [
            f"birth_date={birth_date_value or '-'}",
            f"count={max(count, 0)}",
            f"codes={codes or '-'}",
            f"processing={processing or '-'}",
            f"pcr_image={normalized_images[0] if normalized_images else ''}",
            f"pcr_images={','.join(normalized_images)}",
        ]
    )


def get_or_create_room(db: Session, room_name: str) -> Room:
    normalized_name = room_name.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="鎴块棿鍚嶇О涓嶈兘涓虹┖")

    room = db.query(Room).filter(Room.name == normalized_name).first()
    if room:
        return room

    room = Room(name=normalized_name)
    db.add(room)
    db.flush()
    return room


def get_default_room(db: Session) -> Room:
    return get_or_create_room(db, "未填写房间")


def get_or_create_rack(db: Session, room: Room, rack_name: str) -> Rack:
    normalized_name = rack_name.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="绗兼灦鍚嶇О涓嶈兘涓虹┖")

    rack = (
        db.query(Rack)
        .filter(Rack.room_id == room.id, Rack.name == normalized_name)
        .first()
    )
    if rack:
        return rack

    rack = Rack(name=normalized_name, room_id=room.id)
    db.add(rack)
    db.flush()
    return rack


def get_default_rack(db: Session, room: Room) -> Rack:
    return get_or_create_rack(db, room, "未填写笼架")


def resolve_optional_owner(db: Session, owner_user_id: str) -> User:
    normalized_value = owner_user_id.strip()
    if normalized_value:
        owner = db.get(User, int(normalized_value))
        if owner:
            return owner

    fallback = db.query(User).filter(User.role == "owner").order_by(User.id).first()
    if fallback:
        return fallback

    fallback = db.query(User).filter(User.role == "admin").order_by(User.id).first()
    if fallback:
        return fallback

    raise HTTPException(status_code=400, detail="娌℃湁鍙敤鐨勮礋璐ｄ汉")


def visible_users_query(db: Session):
    return db.query(User).filter(User.name != "已删除用户")


def get_deleted_user(db: Session) -> User:
    deleted_user = db.query(User).filter(User.name == "已删除用户").first()
    if deleted_user:
        return deleted_user

    deleted_user = User(name="已删除用户", role="owner", phone=None)
    db.add(deleted_user)
    db.flush()
    return deleted_user


def serialize_birth_record_for_bootstrap(birth_record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": birth_record["id"],
        "created_at": birth_record["created_at"].isoformat() if birth_record["created_at"] else None,
        "operator": birth_record["operator"],
        "birth_date": str(birth_record["birth_date"] or "-"),
        "count": int(birth_record["count"] or 0),
        "codes": str(birth_record["codes"] or "-"),
        "processing": str(birth_record["processing"] or "-"),
        "note": birth_record["note"] or "",
    }


def serialize_bootstrap_cage(cage: Cage) -> dict[str, Any]:
    return {
        "id": cage.id,
        "cage_code": cage.cage_code,
        "strain": cage.strain,
        "male_genotype": cage.male_genotype,
        "female_genotype": cage.female_genotype,
        "status": cage.status,
        "pup_count": cage.pup_count,
        "owner_user_id": cage.owner_user_id,
        "owner": cage.owner.name,
        "room_id": cage.room_id,
        "room": cage.room.name,
        "rack_id": cage.rack_id,
        "rack": cage.rack.name,
        "male_code": cage.male_code,
        "female_code": cage.female_code,
        "setup_date": cage.setup_date.isoformat() if cage.setup_date else "",
        "birth_date": cage.birth_date.isoformat() if cage.birth_date else "",
        "notes": cage.notes,
        "updated_at": cage.updated_at.isoformat() if cage.updated_at else None,
        "birth_records": [
            serialize_birth_record_for_bootstrap(record)
            for record in build_birth_records(cage)
        ],
    }


def build_bootstrap_payload(db: Session) -> dict[str, Any]:
    cages = (
        db.query(Cage)
        .options(
            joinedload(Cage.owner),
            joinedload(Cage.room),
            joinedload(Cage.rack),
            joinedload(Cage.usage_records).joinedload(UsageRecord.user),
        )
        .order_by(Cage.cage_code)
        .all()
    )
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "users": [
            {"id": user.id, "name": user.name, "role": user.role}
            for user in visible_users_query(db).order_by(User.name).all()
        ],
        "rooms": [
            {"id": room.id, "name": room.name}
            for room in db.query(Room).order_by(Room.name).all()
        ],
        "cages": [serialize_bootstrap_cage(cage) for cage in cages],
        "status_options": STATUS_OPTIONS,
        "action_options": ACTION_OPTIONS,
    }


def resolve_operator(db: Session, operator_name: str) -> User:
    user = db.query(User).filter(User.name == operator_name).first()
    if user:
        return user

    fallback = db.query(User).filter(User.role == "owner").order_by(User.id).first()
    if fallback:
        return fallback

    fallback = db.query(User).filter(User.role == "admin").order_by(User.id).first()
    if fallback:
        return fallback

    raise HTTPException(status_code=400, detail="?????????")


def resolve_user_for_sync(db: Session, payload: dict[str, Any], operator: User) -> User:
    owner_user_id = str(payload.get("owner_user_id") or "").strip()
    if owner_user_id:
        owner = db.get(User, int(owner_user_id))
        if owner:
            return owner

    owner_name = str(payload.get("owner_name") or "").strip()
    if owner_name:
        owner = db.query(User).filter(User.name == owner_name).first()
        if owner:
            return owner

    return operator


def check_cage_version(cage: Cage, payload: dict[str, Any]) -> bool:
    expected = str(payload.get("base_updated_at") or "").strip()
    current = cage.updated_at.isoformat() if cage.updated_at else ""
    return not expected or expected == current


def sync_add_usage_record(db: Session, cage: Cage, operator: User, payload: dict[str, Any]) -> None:
    db.add(
        UsageRecord(
            cage_id=cage.id,
            user_id=operator.id,
            action=str(payload.get("action") or "备注"),
            purpose=str(payload.get("purpose") or "").strip() or None,
            note=str(payload.get("note") or "").strip() or None,
        )
    )


def sync_update_cage_fields(db: Session, cage: Cage, operator: User, payload: dict[str, Any]) -> None:
    if not check_cage_version(cage, payload):
        raise ValueError("璇ョ浣嶅凡琚叾浠栦汉鏇存柊锛岃鍒锋柊鍚庡啀鍚屾")
    if not can_edit_cage(operator, cage):
        raise PermissionError("浣犳病鏈夋潈闄愪慨鏀硅绗间綅")

    room_name = str(payload.get("room_name") or "").strip()
    rack_name = str(payload.get("rack_name") or "").strip()
    if room_name or rack_name:
        room = get_or_create_room(db, room_name) if room_name else get_default_room(db)
        rack = get_or_create_rack(db, room, rack_name) if rack_name else get_default_rack(db, room)
        cage.room_id = room.id
        cage.rack_id = rack.id

    male_genotype, female_genotype = resolve_genotypes(
        payload.get("male_genotype"),
        payload.get("female_genotype"),
        payload.get("strain"),
    )
    cage.male_genotype = male_genotype or None
    cage.female_genotype = female_genotype or None
    cage.strain = derive_legacy_strain(male_genotype, female_genotype, payload.get("strain"))
    cage.male_code = str(payload.get("male_code") or "").strip() or None
    cage.female_code = str(payload.get("female_code") or "").strip() or None
    setup_date = str(payload.get("setup_date") or "").strip()
    cage.setup_date = parse_optional_date(setup_date) if setup_date else None
    cage.status = str(payload.get("status") or "").strip()
    cage.notes = str(payload.get("notes") or "").strip() or None

    db.add(
        UsageRecord(
            cage_id=cage.id,
            user_id=operator.id,
            action="备注",
            purpose="离线同步更新笼位字段",
            note="离线同步更新笼位信息",
        )
    )


def sync_add_birth_record(db: Session, cage: Cage, operator: User, payload: dict[str, Any]) -> UsageRecord:
    if not can_edit_cage(operator, cage):
        raise PermissionError("浣犳病鏈夋潈闄愪慨鏀硅绗间綅")

    birth_date_value = str(payload.get("birth_date") or "").strip()
    parsed_birth_date = parse_optional_date(birth_date_value) if birth_date_value else None
    count = max(int(payload.get("count") or 0), 0)
    if parsed_birth_date:
        cage.birth_date = parsed_birth_date
    if count:
        cage.pup_count = max(cage.pup_count, 0) + count

    record = UsageRecord(
        cage_id=cage.id,
        user_id=operator.id,
        action="新生登记",
        purpose=serialize_birth_purpose(
            birth_date_value,
            count,
            str(payload.get("codes") or "").strip(),
            "-",
            "",
        ),
        note=str(payload.get("note") or "").strip() or None,
    )
    db.add(record)
    db.flush()
    return record


def sync_update_birth_processing(db: Session, cage: Cage, operator: User, payload: dict[str, Any]) -> None:
    if not can_edit_cage(operator, cage):
        raise PermissionError("浣犳病鏈夋潈闄愪慨鏀硅绗间綅")

    record_id = payload.get("birth_record_id")
    if record_id is None:
        raise ValueError("???????????")

    record = (
        db.query(UsageRecord)
        .filter(UsageRecord.id == int(record_id), UsageRecord.cage_id == cage.id)
        .first()
    )
    if not record:
        raise ValueError("鏈壘鍒拌鏇存柊澶勭悊鐨勬柊鐢熼紶璁板綍")

    parsed = parse_birth_record(record)
    if not parsed:
        raise ValueError("???????????")

    parsed_images = list(parsed.get("pcr_images") or [])
    record.purpose = serialize_birth_purpose(
        str(parsed["birth_date"]),
        int(parsed["count"]),
        str(parsed["codes"]),
        str(payload.get("processing") or "").strip() or "-",
        parsed_images[0] if parsed_images else "",
        parsed_images,
    )


def sync_create_cage(db: Session, operator: User, payload: dict[str, Any]) -> Cage:
    if operator.role not in {"admin", "owner"}:
        raise PermissionError("??????????????")

    cage_code = str(payload.get("cage_code") or "").strip().upper()
    if not cage_code:
        raise ValueError("绗间綅缂栧彿涓嶈兘涓虹┖")
    if db.query(Cage).filter(Cage.cage_code == cage_code).first():
        raise ValueError(f"?? {cage_code} ???")

    owner = operator if operator.role == "owner" else resolve_user_for_sync(db, payload, operator)
    room_name = str(payload.get("room_name") or "").strip()
    rack_name = str(payload.get("rack_name") or "").strip()
    room = get_or_create_room(db, room_name) if room_name else get_default_room(db)
    rack = get_or_create_rack(db, room, rack_name) if rack_name else get_default_rack(db, room)
    setup_date = str(payload.get("setup_date") or "").strip()
    male_genotype, female_genotype = resolve_genotypes(
        payload.get("male_genotype"),
        payload.get("female_genotype"),
        payload.get("strain"),
    )

    cage = Cage(
        cage_code=cage_code,
        room_id=room.id,
        rack_id=rack.id,
        owner_user_id=owner.id,
        strain=derive_legacy_strain(male_genotype, female_genotype, payload.get("strain")),
        male_genotype=male_genotype or None,
        female_genotype=female_genotype or None,
        male_code=str(payload.get("male_code") or "").strip() or None,
        female_code=str(payload.get("female_code") or "").strip() or None,
        setup_date=parse_optional_date(setup_date) if setup_date else None,
        pup_count=max(int(payload.get("pup_count") or 0), 0),
        status=str(payload.get("status") or "").strip(),
        notes=str(payload.get("notes") or "").strip() or None,
    )
    db.add(cage)
    db.flush()
    db.add(
        UsageRecord(
            cage_id=cage.id,
            user_id=operator.id,
            action="新增",
            purpose="离线同步新增笼位",
            note=f"新增笼位 {cage.cage_code}",
        )
    )
    return cage


def process_sync_item(db: Session, item: SyncItem) -> dict[str, Any]:
    existing = db.query(SyncOperation).filter(SyncOperation.op_id == item.op_id).first()
    if existing:
        return {
            "op_id": item.op_id,
            "status": "duplicate",
            "message": "重复导入，已跳过",
        }

    operator = resolve_operator(db, item.operator_name)
    payload = item.payload or {}
    action_type = item.action_type
    if action_type == "record_usage":
        action_type = "add_usage_record"
    elif action_type == "update_cage":
        action_type = "update_cage_fields"
    sync_payload = dict(payload)

    try:
        if action_type == "create_cage":
            sync_create_cage(db, operator, payload)
        else:
            cage = db.query(Cage).filter(Cage.cage_code == item.cage_code).first()
            if not cage:
                return {
                    "op_id": item.op_id,
                    "status": "failed",
                    "message": f"未找到笼位：{item.cage_code}",
                }

            if action_type == "add_usage_record":
                sync_add_usage_record(db, cage, operator, payload)
            elif action_type == "update_cage_fields":
                sync_update_cage_fields(db, cage, operator, payload)
            elif action_type == "add_birth_record":
                record = sync_add_birth_record(db, cage, operator, payload)
                sync_payload["_created_record_id"] = record.id
            elif action_type == "update_birth_processing":
                sync_update_birth_processing(db, cage, operator, payload)
            else:
                return {
                    "op_id": item.op_id,
                    "status": "failed",
                    "message": f"不支持的动作类型：{item.action_type}",
                }

        db.add(
            SyncOperation(
                op_id=item.op_id,
                action_type=action_type,
                cage_code=item.cage_code,
                operator_name=item.operator_name,
                payload=sync_payload,
                client_created_at=item.client_created_at,
                sync_result="success",
            )
        )
        db.commit()
        return {
            "op_id": item.op_id,
            "status": "success",
            "message": "同步成功",
        }
    except (PermissionError, ValueError) as error:
        db.rollback()
        return {
            "op_id": item.op_id,
            "status": "conflict",
            "message": str(error),
        }


@app.get("/", response_class=HTMLResponse)
def offline_entry(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    return templates.TemplateResponse(
        request=request,
        name="offline.html",
        context=build_context(
            request,
            db,
            {
                "bootstrap_payload": build_bootstrap_payload(db),
                "announcements": load_announcements(db),
                "offline_operator": {
                    "id": current_user.id,
                    "name": current_user.name,
                    "role": current_user.role,
                }
                if current_user
                else None,
            },
        ),
    )


@app.get("/dashboard", response_class=HTMLResponse)
def home(
    request: Request,
    q: str = "",
    room_id: str = "",
    owner_id: str = "",
    status_value: str = "",
    generation_alert: str = "",
    infertility_alert: str = "",
    overcrowding_alert: str = "",
    import_status: str = "",
    import_message: str = "",
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    selected_room_id = int(room_id) if room_id.strip() else None
    selected_owner_id = int(owner_id) if owner_id.strip() else None
    generation_alert = generation_alert.strip().lower()
    infertility_alert = infertility_alert.strip().lower()
    overcrowding_alert = overcrowding_alert.strip().lower()
    query = (
        db.query(Cage)
        .join(Cage.owner)
        .options(
            joinedload(Cage.owner),
            joinedload(Cage.room),
            joinedload(Cage.rack),
            joinedload(Cage.usage_records).joinedload(UsageRecord.user),
        )
        .order_by(Cage.cage_code)
    )

    for term in split_search_terms(q):
        like_value = f"%{term}%"
        query = query.filter(
            or_(
                Cage.cage_code.ilike(like_value),
                Cage.strain.ilike(like_value),
                Cage.male_genotype.ilike(like_value),
                Cage.female_genotype.ilike(like_value),
                User.name.ilike(like_value),
            )
        )
    if selected_room_id:
        query = query.filter(Cage.room_id == selected_room_id)
    if selected_owner_id:
        query = query.filter(Cage.owner_user_id == selected_owner_id)
    if status_value:
        query = query.filter(Cage.status == status_value)

    cages = query.all()
    today = datetime.now().date()
    generation_alerts = {
        cage.id: needs_generation_alert(cage, today) for cage in cages
    }
    overcrowding_alerts = {
        cage.id: needs_overcrowding_alert(cage, today) for cage in cages
    }
    infertility_alerts = {
        cage.id: needs_infertility_alert(cage, today) for cage in cages
    }
    if generation_alert == "yes":
        cages = [cage for cage in cages if generation_alerts.get(cage.id)]
    elif generation_alert == "no":
        cages = [cage for cage in cages if not generation_alerts.get(cage.id)]
    if infertility_alert == "yes":
        cages = [cage for cage in cages if infertility_alerts.get(cage.id)]
    elif infertility_alert == "no":
        cages = [cage for cage in cages if not infertility_alerts.get(cage.id)]
    if overcrowding_alert == "yes":
        cages = [cage for cage in cages if overcrowding_alerts.get(cage.id)]
    elif overcrowding_alert == "no":
        cages = [cage for cage in cages if not overcrowding_alerts.get(cage.id)]
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=build_context(
            request,
            db,
            {
                "cages": cages,
                "announcements": load_announcements(db),
                "birth_summaries": {cage.id: build_birth_summary(cage) for cage in cages},
                "generation_alerts": generation_alerts,
                "overcrowding_alerts": overcrowding_alerts,
                "infertility_alerts": infertility_alerts,
                "rooms": (
                    db.query(Room)
                    .join(Cage, Cage.room_id == Room.id)
                    .distinct()
                    .order_by(Room.name)
                    .all()
                ),
                "owners": visible_users_query(db).order_by(User.name).all(),
                "status_options": STATUS_OPTIONS,
                "filters": {
                    "q": q,
                    "room_id": selected_room_id,
                    "owner_id": selected_owner_id,
                    "status_value": status_value,
                    "generation_alert": generation_alert,
                    "infertility_alert": infertility_alert,
                    "overcrowding_alert": overcrowding_alert,
                },
                "import_status": import_status,
                "import_message": import_message,
                "add_cage_href": "/cages/new"
                if current_user and current_user.role in {"admin", "owner"}
                else "/login",
            },
        ),
    )


@app.get("/json-import", response_class=HTMLResponse)
def json_import_page(
    request: Request,
    import_status: str = "",
    import_message: str = "",
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(
        request=request,
        name="json_import.html",
        context=build_context(
            request,
            db,
            {
                "import_status": import_status,
                "import_message": import_message,
            },
        ),
    )


@app.get("/cages/new", response_class=HTMLResponse)
def new_cage_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if user.role not in {"admin", "owner"}:
        raise HTTPException(status_code=403, detail="??????????????")
    return templates.TemplateResponse(
        request=request,
        name="new_cage.html",
        context=build_context(
            request,
            db,
            {
                "rooms": db.query(Room).order_by(Room.name).all(),
                "racks": db.query(Rack).options(joinedload(Rack.room)).order_by(Rack.name).all(),
                "users": visible_users_query(db).order_by(User.name).all(),
                "status_options": STATUS_OPTIONS,
                "can_choose_owner": user.role == "admin",
                "fixed_owner": user,
                "male_code_values": [""],
                "female_code_values": [""],
            },
        ),
    )


@app.post("/cages/create")
def create_cage(
    request: Request,
    cage_code: str = Form(""),
    room_name: str = Form(""),
    rack_name: str = Form(""),
    owner_user_id: str = Form(""),
    male_genotype: str = Form(""),
    female_genotype: str = Form(""),
    strain: str = Form(""),
    male_code: list[str] = Form([]),
    female_code: list[str] = Form([]),
    setup_date: str = Form(""),
    birth_date: str = Form(""),
    wean_date: str = Form(""),
    pup_count: int = Form(0),
    status_value: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if user.role not in {"admin", "owner"}:
        raise HTTPException(status_code=403, detail="??????????????")

    cage_code = cage_code.strip().upper()
    if not cage_code:
        raise HTTPException(status_code=400, detail="绗间綅缂栧彿涓嶈兘涓虹┖")
    if db.query(Cage).filter(Cage.cage_code == cage_code).first():
        raise HTTPException(status_code=400, detail="???????")

    owner = user if user.role == "owner" else resolve_optional_owner(db, owner_user_id)
    room = get_or_create_room(db, room_name) if room_name.strip() else get_default_room(db)
    rack = get_or_create_rack(db, room, rack_name) if rack_name.strip() else get_default_rack(db, room)
    resolved_male_genotype, resolved_female_genotype = resolve_genotypes(
        male_genotype,
        female_genotype,
        strain,
    )

    cage = Cage(
        cage_code=cage_code,
        room_id=room.id,
        rack_id=rack.id,
        owner_user_id=owner.id,
        strain=derive_legacy_strain(resolved_male_genotype, resolved_female_genotype, strain),
        male_genotype=resolved_male_genotype or None,
        female_genotype=resolved_female_genotype or None,
        male_code=join_parent_codes(male_code),
        female_code=join_parent_codes(female_code),
        setup_date=parse_optional_date(setup_date),
        birth_date=parse_optional_date(birth_date),
        wean_date=parse_optional_date(wean_date),
        pup_count=max(pup_count, 0),
        status=status_value.strip(),
        notes=notes.strip() or None,
    )
    db.add(cage)
    db.flush()
    db.add(
        UsageRecord(
            cage_id=cage.id,
            user_id=user.id,
            action="新增",
            purpose="新增笼位",
            note=f"新增笼位 {cage.cage_code}",
        )
    )
    db.commit()
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/cages/{cage_id}/births")
def add_birth_record(
    cage_id: int,
    request: Request,
    birth_date_value: str = Form(""),
    litter_count: int = Form(0),
    litter_codes: str = Form(""),
    litter_note: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    cage = db.get(Cage, cage_id)
    if not cage:
        raise HTTPException(status_code=404, detail="?????")
    if not can_edit_cage(user, cage):
        raise HTTPException(status_code=403, detail="??????????")

    parsed_birth_date = parse_optional_date(birth_date_value) if birth_date_value.strip() else None
    count = max(litter_count, 0)
    if parsed_birth_date:
        cage.birth_date = parsed_birth_date
    if count:
        cage.pup_count = max(cage.pup_count, 0) + count

    db.add(
        UsageRecord(
            cage_id=cage.id,
            user_id=user.id,
            action="新生登记",
            purpose=serialize_birth_purpose(
                birth_date_value.strip(),
                count,
                litter_codes.strip(),
                "-",
                "",
            ),
            note=litter_note.strip() or None,
        )
    )
    db.commit()
    return RedirectResponse(url=f"/cages/{cage_id}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/cages/{cage_id}/births/{record_id}/processing")
def update_birth_processing(
    cage_id: int,
    record_id: int,
    request: Request,
    processing: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    cage = db.get(Cage, cage_id)
    if not cage:
        raise HTTPException(status_code=404, detail="?????")
    if not can_edit_cage(user, cage):
        raise HTTPException(status_code=403, detail="??????????")

    record = (
        db.query(UsageRecord)
        .filter(UsageRecord.id == record_id, UsageRecord.cage_id == cage_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="???????")

    parsed = parse_birth_record(record)
    if not parsed:
        raise HTTPException(status_code=400, detail="???????????")

    record.purpose = serialize_birth_purpose(
        str(parsed["birth_date"]),
        int(parsed["count"]),
        str(parsed["codes"]),
        processing.strip() or "-",
        str(parsed["pcr_image"]),
    )
    db.commit()
    return RedirectResponse(url=f"/cages/{cage_id}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/cages/{cage_id}/births/{record_id}/pcr-image")
def update_birth_pcr_image(
    cage_id: int,
    record_id: int,
    request: Request,
    pcr_images: list[UploadFile] | None = File(None),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    cage = db.get(Cage, cage_id)
    if not cage:
        raise HTTPException(status_code=404, detail="?????")
    if not can_edit_cage(user, cage):
        raise HTTPException(status_code=403, detail="浣犳病鏈夋潈闄愪慨鏀硅绗间綅")

    record = (
        db.query(UsageRecord)
        .filter(UsageRecord.id == record_id, UsageRecord.cage_id == cage_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="????????")

    parsed = parse_birth_record(record)
    if not parsed:
        raise HTTPException(status_code=400, detail="???????????")

    image_paths = save_birth_images(pcr_images)
    if image_paths:
        merged_images = list(parsed["pcr_images"]) + image_paths
        record.purpose = serialize_birth_purpose(
            str(parsed["birth_date"]),
            int(parsed["count"]),
            str(parsed["codes"]),
            str(parsed["processing"]),
            pcr_images=merged_images,
        )
        db.commit()

    return RedirectResponse(url=f"/cages/{cage_id}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/cages/{cage_id}/births/{record_id}/pcr-image/delete")
def delete_birth_pcr_image(
    cage_id: int,
    record_id: int,
    request: Request,
    image_path: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    cage = db.get(Cage, cage_id)
    if not cage:
        raise HTTPException(status_code=404, detail="?????")
    if not can_edit_cage(user, cage):
        raise HTTPException(status_code=403, detail="浣犳病鏈夋潈闄愪慨鏀硅绗间綅")

    record = (
        db.query(UsageRecord)
        .filter(UsageRecord.id == record_id, UsageRecord.cage_id == cage_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="????????")

    parsed = parse_birth_record(record)
    if not parsed:
        raise HTTPException(status_code=400, detail="???????????")

    remaining_images = [item for item in parsed["pcr_images"] if item != image_path]
    remove_birth_image(image_path)
    record.purpose = serialize_birth_purpose(
        str(parsed["birth_date"]),
        int(parsed["count"]),
        str(parsed["codes"]),
        str(parsed["processing"]),
        pcr_images=remaining_images,
    )
    db.commit()
    return RedirectResponse(url=f"/cages/{cage_id}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/cages/{cage_id}/births/{record_id}/delete")
def delete_birth_record(
    cage_id: int,
    record_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    cage = db.get(Cage, cage_id)
    if not cage:
        raise HTTPException(status_code=404, detail="?????")
    if not can_edit_cage(user, cage):
        raise HTTPException(status_code=403, detail="浣犳病鏈夋潈闄愪慨鏀硅绗间綅")

    record = (
        db.query(UsageRecord)
        .filter(UsageRecord.id == record_id, UsageRecord.cage_id == cage_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="????????")

    parsed = parse_birth_record(record)
    if not parsed:
        raise HTTPException(status_code=400, detail="???????????")

    cage.pup_count = max(cage.pup_count - parsed["count"], 0)
    remaining_records = [
        item for item in build_birth_records(cage) if item["id"] != record.id
    ]
    if remaining_records:
        latest_birth_date = remaining_records[0]["birth_date"]
        cage.birth_date = (
            parse_optional_date(latest_birth_date)
            if latest_birth_date and latest_birth_date != "-"
            else None
        )
    else:
        cage.birth_date = None

    remove_birth_image(parsed["pcr_image"])
    db.delete(record)
    db.commit()
    return RedirectResponse(url=f"/cages/{cage_id}", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    message: str = "",
    tone: str = "info",
    db: Session = Depends(get_db),
):
    last_login_user = get_last_login_user(request, db)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context=build_context(
            request,
            db,
            {
                "users": visible_users_query(db).order_by(User.role, User.name).all(),
                "last_login_user": last_login_user,
                "message": message,
                "tone": tone,
            },
        ),
    )


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context=build_context(
            request,
            db,
            {},
        ),
    )


@app.post("/register")
def register(
    name: str = Form(...),
    phone: str = Form(""),
    db: Session = Depends(get_db),
):
    normalized_name = name.strip()
    normalized_phone = phone.strip()

    if not normalized_name:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    if db.query(User).filter(User.name == normalized_name).first():
        raise HTTPException(status_code=400, detail="该用户名已存在")

    user = User(
        name=normalized_name,
        role="owner",
        phone=normalized_phone or None,
    )
    db.add(user)
    db.commit()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/login")
def login(
    request: Request,
    user_id: int = Form(...),
    password: str = Form(""),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role == "admin" and not verify_password(password, user.password_hash):
        params = urlencode({"message": "管理员密码错误", "tone": "error"})
        return RedirectResponse(url=f"/login?{params}", status_code=status.HTTP_303_SEE_OTHER)

    client_ip = get_client_ip(request)
    login_memory = db.query(LoginMemory).filter(LoginMemory.ip_address == client_ip).first()
    if not login_memory:
        login_memory = LoginMemory(ip_address=client_ip, user_id=user.id)
        db.add(login_memory)
    else:
        login_memory.user_id = user.id
        login_memory.updated_at = datetime.utcnow()
    db.commit()

    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie("user_id", str(user.id), httponly=True, samesite="lax")
    return response


def build_logout_response() -> RedirectResponse:
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("user_id")
    return response


@app.post("/logout")
def logout():
    return build_logout_response()


@app.get("/logout")
def logout_get():
    return build_logout_response()

@app.get("/users", response_class=HTMLResponse)
def user_management_page(
    request: Request,
    status_message: str = "",
    status_tone: str = "info",
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    users = visible_users_query(db).order_by(User.role, User.name).all()
    return templates.TemplateResponse(
        request=request,
        name="users.html",
        context=build_context(
            request,
            db,
            {
                "users": users,
                "status_message": status_message,
                "status_tone": status_tone,
                "role_options": ["admin", "owner"],
            },
        ),
    )


@app.post("/users/{user_id}/update")
def update_user(
    user_id: int,
    request: Request,
    name: str = Form(...),
    role: str = Form(...),
    phone: str = Form(""),
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="?????")

    normalized_name = name.strip()
    normalized_role = role.strip().lower()
    normalized_phone = phone.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="???????")
    if normalized_role not in {"admin", "owner"}:
        raise HTTPException(status_code=400, detail="瑙掕壊鏃犳晥")

    duplicate = (
        db.query(User)
        .filter(User.name == normalized_name, User.id != user_id)
        .first()
    )
    if duplicate:
        return RedirectResponse(
            url="/users?status_tone=error&status_message=鐢ㄦ埛鍚嶅凡瀛樺湪",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    user.name = normalized_name
    user.role = normalized_role
    user.phone = normalized_phone or None
    db.commit()
    return RedirectResponse(
        url="/users?status_tone=success&status_message=???????",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/users/{user_id}/delete")
def delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    current_admin = require_admin(request, db)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="?????")
    if user.id == current_admin.id:
        return RedirectResponse(
            url="/users?status_tone=error&status_message=涓嶈兘鍒犻櫎褰撳墠鐧诲綍璐﹀彿",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if db.query(Cage).filter(Cage.owner_user_id == user.id).first():
        return RedirectResponse(
            url="/users?status_tone=error&status_message=?????????????",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    deleted_user = get_deleted_user(db)
    if user.id == deleted_user.id:
        return RedirectResponse(
            url="/users?status_tone=error&status_message=绯荤粺淇濈暀璐﹀彿涓嶈兘鍒犻櫎",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    db.query(UsageRecord).filter(UsageRecord.user_id == user.id).update(
        {UsageRecord.user_id: deleted_user.id},
        synchronize_session=False,
    )
    db.query(Announcement).filter(Announcement.user_id == user.id).update(
        {Announcement.user_id: deleted_user.id},
        synchronize_session=False,
    )

    db.delete(user)
    db.commit()
    return RedirectResponse(
        url="/users?status_tone=success&status_message=???????????????",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/announcements")
def create_announcement(
    request: Request,
    content: str = Form(""),
    next_url: str = Form("/dashboard"),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    normalized_content = content.strip()
    if not normalized_content:
        raise HTTPException(status_code=400, detail="鍏憡鍐呭涓嶈兘涓虹┖")

    db.add(Announcement(user_id=user.id, content=normalized_content))
    db.commit()
    redirect_target = next_url.strip() or "/dashboard"
    return RedirectResponse(url=redirect_target, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/announcements/{announcement_id}/delete")
def delete_announcement(
    announcement_id: int,
    request: Request,
    next_url: str = Form("/dashboard"),
    db: Session = Depends(get_db),
):
    require_user(request, db)
    announcement = db.get(Announcement, announcement_id)
    if not announcement:
        raise HTTPException(status_code=404, detail="?????")

    db.delete(announcement)
    db.commit()
    redirect_target = next_url.strip() or "/dashboard"
    return RedirectResponse(url=redirect_target, status_code=status.HTTP_303_SEE_OTHER)


@app.get("/cages/{cage_id}", response_class=HTMLResponse)
def cage_detail(cage_id: int, request: Request, db: Session = Depends(get_db)):
    cage = (
        db.query(Cage)
        .options(
            joinedload(Cage.owner),
            joinedload(Cage.room),
            joinedload(Cage.rack),
            joinedload(Cage.usage_records).joinedload(UsageRecord.user),
        )
        .filter(Cage.id == cage_id)
        .first()
    )
    if not cage:
        raise HTTPException(status_code=404, detail="?????")

    current_user = get_current_user(request, db)
    return templates.TemplateResponse(
        request=request,
        name="cage_detail.html",
        context=build_context(
            request,
            db,
            {
                "cage": cage,
                "record_view": {
                    record.id: {
                        "action": sanitize_record_action(record.action),
                        "purpose": sanitize_record_purpose(record),
                        "note": sanitize_record_note(record),
                    }
                    for record in cage.usage_records
                },
                "birth_records": build_birth_records(cage),
                "cage_tag_image": cage.cage_tag_image,
                "male_code_values": split_parent_codes(cage.male_code),
                "female_code_values": split_parent_codes(cage.female_code),
                "users": visible_users_query(db).order_by(User.name).all(),
                "status_options": STATUS_OPTIONS,
                "action_options": ACTION_OPTIONS,
                "can_edit": bool(current_user and can_edit_cage(current_user, cage)),
            },
        ),
    )


@app.post("/cages/{cage_id}/update")
def update_cage(
    cage_id: int,
    request: Request,
    cage_code: str = Form(...),
    male_genotype: str = Form(""),
    female_genotype: str = Form(""),
    strain: str = Form(""),
    male_code: list[str] = Form([]),
    female_code: list[str] = Form([]),
    setup_date: str = Form(""),
    birth_date: str = Form(""),
    room_name: str = Form(""),
    rack_name: str = Form(""),
    owner_user_id: int = Form(...),
    status_value: str = Form(...),
    pup_count: int = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    cage = db.get(Cage, cage_id)
    if not cage:
        raise HTTPException(status_code=404, detail="?????")
    if not can_edit_cage(user, cage):
        raise HTTPException(status_code=403, detail="??????????")

    cage_code = cage_code.strip().upper()
    if not cage_code:
        raise HTTPException(status_code=400, detail="????????")
    duplicate = db.query(Cage).filter(Cage.cage_code == cage_code, Cage.id != cage_id).first()
    if duplicate:
        raise HTTPException(status_code=400, detail="???????")

    owner = db.get(User, owner_user_id)
    if not owner:
        raise HTTPException(status_code=400, detail="????????")
    if user.role == "admin":
        owner = db.get(User, owner_user_id)
        if not owner:
            raise HTTPException(status_code=400, detail="????????")
        cage.owner_user_id = owner_user_id
    room = get_or_create_room(db, room_name)
    rack = get_or_create_rack(db, room, rack_name)
    resolved_male_genotype, resolved_female_genotype = resolve_genotypes(
        male_genotype,
        female_genotype,
        strain,
    )

    cage.cage_code = cage_code
    cage.strain = derive_legacy_strain(resolved_male_genotype, resolved_female_genotype, strain)
    cage.male_genotype = resolved_male_genotype or None
    cage.female_genotype = resolved_female_genotype or None
    cage.male_code = join_parent_codes(male_code)
    cage.female_code = join_parent_codes(female_code)
    cage.setup_date = parse_optional_date(setup_date)
    cage.birth_date = parse_optional_date(birth_date)
    cage.rack_id = rack.id
    cage.room_id = room.id
    cage.status = status_value
    cage.pup_count = max(pup_count, 0)
    cage.notes = notes.strip() or None

    db.add(
        UsageRecord(
            cage_id=cage.id,
            user_id=user.id,
            action="更新",
            purpose="更新笼位信息",
            note=f"更新笼位 {cage.cage_code} 信息",
        )
    )
    db.commit()
    return RedirectResponse(url=f"/cages/{cage_id}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/cages/{cage_id}/delete")
def delete_cage(cage_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    cage = db.get(Cage, cage_id)
    if not cage:
        raise HTTPException(status_code=404, detail="?????")
    if user.role != "admin" and user.id != cage.owner_user_id:
        raise HTTPException(status_code=403, detail="鍙湁绠＄悊鍛樻垨璇ョ浣嶈礋璐ｄ汉鍙互鍒犻櫎绗间綅")

    db.query(UsageRecord).filter(UsageRecord.cage_id == cage.id).delete()
    db.delete(cage)
    db.commit()
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/cages/{cage_id}/records")
def add_record(
    cage_id: int,
    request: Request,
    action: str = Form(...),
    purpose: str = Form(""),
    note: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    cage = db.get(Cage, cage_id)
    if not cage:
        raise HTTPException(status_code=404, detail="?????")

    db.add(
        UsageRecord(
            cage_id=cage.id,
            user_id=user.id,
            action=action,
            purpose=purpose.strip() or None,
            note=note.strip() or None,
        )
    )
    db.commit()
    return RedirectResponse(url=f"/cages/{cage_id}", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/records", response_class=HTMLResponse)
def record_list(
    request: Request,
    cage_id: int | None = None,
    db: Session = Depends(get_db),
):
    query = (
        db.query(UsageRecord)
        .options(joinedload(UsageRecord.user), joinedload(UsageRecord.cage))
        .order_by(UsageRecord.created_at.desc())
    )
    selected_cage = None
    if cage_id is not None:
        query = query.filter(UsageRecord.cage_id == cage_id)
        selected_cage = db.get(Cage, cage_id)

    records = query.all()
    return templates.TemplateResponse(
        request=request,
        name="records.html",
        context=build_context(
            request,
            db,
            {
                "records": records,
                "record_view": {
                    record.id: {
                        "action": sanitize_record_action(record.action),
                        "purpose": sanitize_record_purpose(record),
                        "note": sanitize_record_note(record),
                    }
                    for record in records
                },
                "selected_cage": selected_cage,
            },
        ),
    )


@app.post("/cages/{cage_id}/tag-image")
def update_cage_tag_image(
    cage_id: int,
    request: Request,
    cage_tag_image: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    cage = db.get(Cage, cage_id)
    if not cage:
        raise HTTPException(status_code=404, detail="?????")
    if not can_edit_cage(user, cage):
        raise HTTPException(status_code=403, detail="浣犳病鏈夋潈闄愪慨鏀硅绗间綅")

    image_path = save_cage_tag_image(cage_tag_image)
    if image_path:
        remove_cage_tag_image(cage.cage_tag_image)
        cage.cage_tag_image = image_path
        db.commit()

    return RedirectResponse(url=f"/cages/{cage_id}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/cages/{cage_id}/tag-image/delete")
def delete_cage_tag_image(
    cage_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    cage = db.get(Cage, cage_id)
    if not cage:
        raise HTTPException(status_code=404, detail="?????")
    if not can_edit_cage(user, cage):
        raise HTTPException(status_code=403, detail="浣犳病鏈夋潈闄愪慨鏀硅绗间綅")

    remove_cage_tag_image(cage.cage_tag_image)
    cage.cage_tag_image = None
    db.commit()
    return RedirectResponse(url=f"/cages/{cage_id}", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/cages/{cage_id}/tag-image/view", response_class=HTMLResponse)
def cage_tag_image_view(cage_id: int, request: Request, db: Session = Depends(get_db)):
    cage = db.get(Cage, cage_id)
    if not cage or not cage.cage_tag_image:
        raise HTTPException(status_code=404, detail="???????")

    return templates.TemplateResponse(
        request=request,
        name="pcr_image_view.html",
        context=build_context(
            request,
            db,
            {
                "image_title": "绗肩墝鍥剧墖棰勮",
                "image_subtitle": cage.cage_code,
                "image_path": cage.cage_tag_image,
                "image_index": "",
            },
        ),
    )


@app.get("/birth-images/view/{record_id}/{image_index}", response_class=HTMLResponse)
def birth_image_view(
    record_id: int,
    image_index: int,
    request: Request,
    db: Session = Depends(get_db),
):
    record = (
        db.query(UsageRecord)
        .options(joinedload(UsageRecord.cage), joinedload(UsageRecord.user))
        .filter(UsageRecord.id == record_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="PCR ???????")

    parsed = parse_birth_record(record)
    if not parsed:
        raise HTTPException(status_code=404, detail="杩欐潯璁板綍娌℃湁PCR鍥剧墖")

    images = parsed["pcr_images"]
    if image_index < 0 or image_index >= len(images):
        raise HTTPException(status_code=404, detail="?????")

    return templates.TemplateResponse(
        request=request,
        name="pcr_image_view.html",
        context=build_context(
            request,
            db,
            {
                "image_title": f"PCR鍥剧墖棰勮 {image_index + 1}",
                "image_subtitle": f"{record.cage.cage_code} | {record.created_at.strftime('%Y-%m-%d %H:%M')}",
                "image_path": images[image_index],
            },
        ),
    )


@app.get("/health")
def health():
    return {
        "status": "ok",
        "server_time": datetime.utcnow().isoformat(),
    }


@app.get("/api/bootstrap")
def api_bootstrap(db: Session = Depends(get_db)):
    return build_bootstrap_payload(db)


@app.get("/exports/bootstrap.json", include_in_schema=False)
def export_bootstrap_json(db: Session = Depends(get_db)):
    payload = build_bootstrap_payload(db)
    return JSONResponse(
        content=payload,
        headers={
            "Content-Disposition": 'attachment; filename="mice-manage-bootstrap.json"'
        },
    )


@app.post("/api/sync")
def api_sync(payload: SyncRequest, db: Session = Depends(get_db)):
    results = [process_sync_item(db, item) for item in payload.items]
    return summarize_sync_results(results)


@app.post("/imports/sync-json")
async def import_sync_json(
    request: Request,
    file: UploadFile = File(...),
    next_url: str = Form("/dashboard"),
    db: Session = Depends(get_db),
):
    if not get_current_user(request, db):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    try:
        raw_content = await file.read()
        payload_data = json.loads(raw_content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        query = urlencode(
            {
                "import_status": "error",
                "import_message": "导入失败：文件不是有效的 UTF-8 JSON",
            }
        )
        return RedirectResponse(
            url=f"{next_url}?{query}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if isinstance(payload_data, dict) and "items" not in payload_data and "cages" in payload_data:
        query = urlencode(
            {
                "import_status": "error",
                "import_message": "你上传的是基础数据 JSON。这个页面只能导入待同步 JSON，请上传 mice-manage-sync-*.json 文件。",
            }
        )
        return RedirectResponse(
            url=f"{next_url}?{query}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    try:
        sync_request = SyncRequest(**payload_data)
    except Exception:
        query = urlencode(
            {
                "import_status": "error",
                "import_message": "导入失败：JSON 缺少 items 数组，或文件结构不是待同步 JSON。",
            }
        )
        return RedirectResponse(
            url=f"{next_url}?{query}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    results = [process_sync_item(db, item) for item in sync_request.items]
    summary = summarize_sync_results(results)
    query = urlencode(
        {
            "import_status": "success" if summary["failed_count"] == 0 else "warn",
            "import_message": (
                f"导入完成：成功 {summary['success_count']} 条，"
                f"失败 {summary['failed_count']} 条，"
                f"重复 {summary['duplicate_count']} 条",
            ),
        }
    )
    return RedirectResponse(
        url=f"{next_url}?{query}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/api/cages")
def api_cages(db: Session = Depends(get_db)):
    cages = (
        db.query(Cage)
        .options(joinedload(Cage.owner), joinedload(Cage.room), joinedload(Cage.rack))
        .order_by(Cage.cage_code)
        .all()
    )
    return [
        {
            "id": cage.id,
            "cage_code": cage.cage_code,
            "room": cage.room.name,
            "rack": cage.rack.name,
            "owner": cage.owner.name,
            "strain": cage.strain,
            "male_genotype": cage.male_genotype,
            "female_genotype": cage.female_genotype,
            "status": cage.status,
            "pup_count": cage.pup_count,
            "notes": cage.notes,
        }
        for cage in cages
    ]


@app.get("/api/cages/{cage_id}")
def api_cage_detail(cage_id: int, db: Session = Depends(get_db)):
    cage = (
        db.query(Cage)
        .options(joinedload(Cage.owner), joinedload(Cage.room), joinedload(Cage.rack))
        .filter(Cage.id == cage_id)
        .first()
    )
    if not cage:
        raise HTTPException(status_code=404, detail="?????")
    return {
        "id": cage.id,
        "cage_code": cage.cage_code,
        "room": cage.room.name,
        "rack": cage.rack.name,
        "owner": cage.owner.name,
        "strain": cage.strain,
        "male_genotype": cage.male_genotype,
        "female_genotype": cage.female_genotype,
        "male_code": cage.male_code,
        "female_code": cage.female_code,
        "setup_date": cage.setup_date,
        "birth_date": cage.birth_date,
        "wean_date": cage.wean_date,
        "pup_count": cage.pup_count,
        "status": cage.status,
        "notes": cage.notes,
    }


@app.get("/api/records")
def api_records(db: Session = Depends(get_db)):
    records = (
        db.query(UsageRecord)
        .options(joinedload(UsageRecord.user), joinedload(UsageRecord.cage))
        .order_by(UsageRecord.created_at.desc())
        .all()
    )
    return [
        {
            "id": record.id,
            "cage_code": record.cage.cage_code,
            "user": record.user.name,
            "action": record.action,
            "purpose": record.purpose,
            "note": record.note,
            "created_at": record.created_at,
        }
        for record in records
    ]


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == status.HTTP_303_SEE_OTHER:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    db = SessionLocal()
    try:
        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context=build_context(
                request,
                db,
                {"status_code": exc.status_code, "detail": exc.detail},
            ),
            status_code=exc.status_code,
        )
    finally:
        db.close()
