from datetime import date

from sqlalchemy.orm import Session

from .models import Cage, Rack, Room, UsageRecord, User
from .security import hash_password


def seed_data(db: Session) -> None:
    if db.query(User).first():
        return

    admin = User(
        name="任老师",
        role="admin",
        phone="13800000001",
        password_hash=hash_password("Renlab123"),
    )
    owner = User(name="张同学", role="owner", phone="13800000002")
    db.add_all([admin, owner])
    db.flush()

    room_a = Room(name="SPF-A房间")
    room_b = Room(name="SPF-B房间")
    db.add_all([room_a, room_b])
    db.flush()

    rack_a1 = Rack(name="A架-1层", room_id=room_a.id)
    rack_a2 = Rack(name="A架-2层", room_id=room_a.id)
    rack_b1 = Rack(name="B架-1层", room_id=room_b.id)
    db.add_all([rack_a1, rack_a2, rack_b1])
    db.flush()

    cage_1 = Cage(
        cage_code="A1-01",
        room_id=room_a.id,
        rack_id=rack_a1.id,
        owner_user_id=owner.id,
        strain="C57BL/6",
        male_code="M-24001",
        female_code="F-24009",
        setup_date=date(2026, 3, 20),
        birth_date=date(2026, 3, 24),
        pup_count=6,
        status="繁殖",
        notes="第一窝，状态稳定。",
    )
    cage_2 = Cage(
        cage_code="A1-02",
        room_id=room_a.id,
        rack_id=rack_a1.id,
        owner_user_id=owner.id,
        strain="APP/PS1",
        male_code="M-13008",
        female_code="F-13017",
        setup_date=date(2026, 3, 18),
        pup_count=0,
        status="繁殖",
        notes="本周继续观察配种情况。",
    )
    cage_3 = Cage(
        cage_code="B1-03",
        room_id=room_b.id,
        rack_id=rack_b1.id,
        owner_user_id=admin.id,
        strain="BALB/c",
        male_code="M-55001",
        female_code="F-55004",
        setup_date=date(2026, 3, 10),
        wean_date=date(2026, 3, 22),
        pup_count=4,
        status="实验",
        notes="已断奶，可按需登记取用。",
    )
    db.add_all([cage_1, cage_2, cage_3])
    db.flush()

    records = [
        UsageRecord(
            cage_id=cage_1.id,
            user_id=owner.id,
            action="建笼",
            purpose="建立繁殖笼",
            note="完成配对。",
        ),
        UsageRecord(
            cage_id=cage_3.id,
            user_id=owner.id,
            action="查看",
            purpose="日常巡查",
            note="观察状态正常。",
        ),
    ]
    db.add_all(records)
    db.commit()
