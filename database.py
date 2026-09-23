"""
Supabase data layer for The Betta Studio.
Replaces the old SQLite version.

All functions return Python dicts (or lists of dicts) for easy
consumption by Streamlit views.
"""
from typing import Optional
from modules.supabase_client import get_supabase


# ============================================================
# TANKS
# ============================================================
def add_tank(tag_id: str, name: str, tank_type: str,
             capacity_liters: Optional[float] = None,
             status: str = "empty",
             location_note: Optional[str] = None,
             photo_url: Optional[str] = None,
             qr_url: Optional[str] = None,
             notes: Optional[str] = None) -> Optional[dict]:
    """Insert a new tank. Returns the created row or None."""
    data = {
        "tag_id": tag_id,
        "name": name,
        "tank_type": tank_type,
        "capacity_liters": capacity_liters,
        "status": status,
        "location_note": location_note,
        "photo_url": photo_url,
        "qr_url": qr_url,
        "notes": notes,
    }
    data = {k: v for k, v in data.items() if v is not None}
    res = get_supabase().table("tanks").insert(data).execute()
    return res.data[0] if res.data else None


def get_tanks(status: Optional[str] = None,
              tank_type: Optional[str] = None) -> list[dict]:
    """List tanks, optionally filtered."""
    q = get_supabase().table("tanks").select("*")
    if status:
        q = q.eq("status", status)
    if tank_type:
        q = q.eq("tank_type", tank_type)
    return q.order("created_at", desc=True).execute().data


def get_tank_by_id(tank_id: str) -> Optional[dict]:
    res = get_supabase().table("tanks").select("*").eq("id", tank_id).execute()
    return res.data[0] if res.data else None


def get_tank_by_tag(tag_id: str) -> Optional[dict]:
    res = get_supabase().table("tanks").select("*").eq("tag_id", tag_id).execute()
    return res.data[0] if res.data else None


def update_tank(tank_id: str, **fields) -> Optional[dict]:
    res = get_supabase().table("tanks").update(fields).eq("id", tank_id).execute()
    return res.data[0] if res.data else None


def delete_tank(tank_id: str) -> bool:
    res = get_supabase().table("tanks").delete().eq("id", tank_id).execute()
    return bool(res.data)


# ============================================================
# FISH
# ============================================================
def add_fish(tag_id: Optional[str] = None,
             name: Optional[str] = None,
             variety: Optional[str] = None,
             gender: str = "unknown",
             stage: str = "fry",
             status: str = "active",
             birth_date: Optional[str] = None,
             hatch_date: Optional[str] = None,
             sire_id: Optional[str] = None,
             dam_id: Optional[str] = None,
             batch_id: Optional[str] = None,
             batch_tag: Optional[str] = None,
             tank_id: Optional[str] = None,
             photo_url: Optional[str] = None,
             qr_url: Optional[str] = None,
             notes: Optional[str] = None) -> Optional[dict]:
    """Insert a new fish record. Returns the created row."""
    data = {
        "tag_id": tag_id,
        "name": name,
        "variety": variety,
        "gender": gender,
        "stage": stage,
        "status": status,
        "birth_date": birth_date,
        "hatch_date": hatch_date,
        "sire_id": sire_id,
        "dam_id": dam_id,
        "batch_id": batch_id,
        "batch_tag": batch_tag,
        "tank_id": tank_id,
        "photo_url": photo_url,
        "qr_url": qr_url,
        "notes": notes,
    }
    data = {k: v for k, v in data.items() if v is not None}
    res = get_supabase().table("fish").insert(data).execute()
    return res.data[0] if res.data else None


def get_fish(stage: Optional[str] = None,
             status: Optional[str] = None,
             gender: Optional[str] = None,
             variety: Optional[str] = None,
             limit: int = 500) -> list[dict]:
    """List fish, optionally filtered."""
    q = get_supabase().table("fish").select("*")
    if stage:
        q = q.eq("stage", stage)
    if status:
        q = q.eq("status", status)
    if gender:
        q = q.eq("gender", gender)
    if variety:
        q = q.eq("variety", variety)
    return q.order("created_at", desc=True).limit(limit).execute().data


def get_fish_by_id(fish_id: str) -> Optional[dict]:
    res = get_supabase().table("fish").select("*").eq("id", fish_id).execute()
    return res.data[0] if res.data else None


def get_fish_by_tag(tag_id: str) -> Optional[dict]:
    res = get_supabase().table("fish").select("*").eq("tag_id", tag_id).execute()
    return res.data[0] if res.data else None


def get_fish_by_batch(batch_id: str) -> list[dict]:
    return (get_supabase().table("fish").select("*")
            .eq("batch_id", batch_id)
            .order("created_at").execute().data)


def get_breeders(gender: Optional[str] = None) -> list[dict]:
    """Get fish with stage='breeder'."""
    q = get_supabase().table("fish").select("*").eq("stage", "breeder")
    if gender:
        q = q.eq("gender", gender)
    return q.order("tag_id").execute().data


def update_fish(fish_id: str, **fields) -> Optional[dict]:
    res = get_supabase().table("fish").update(fields).eq("id", fish_id).execute()
    return res.data[0] if res.data else None


def delete_fish(fish_id: str) -> bool:
    res = get_supabase().table("fish").delete().eq("id", fish_id).execute()
    return bool(res.data)


# ============================================================
# SPAWNS
# ============================================================
def add_spawn(spawn_code: str,
              sire_id: Optional[str] = None,
              dam_id: Optional[str] = None,
              pair_date: Optional[str] = None,
              spawn_date: Optional[str] = None,
              hatch_date: Optional[str] = None,
              eggs_count: int = 0,
              fry_count: int = 0,
              outcome: str = "pending",
              tank_id: Optional[str] = None,
              notes: Optional[str] = None) -> Optional[dict]:
    data = {
        "spawn_code": spawn_code,
        "sire_id": sire_id,
        "dam_id": dam_id,
        "pair_date": pair_date,
        "spawn_date": spawn_date,
        "hatch_date": hatch_date,
        "eggs_count": eggs_count,
        "fry_count": fry_count,
        "outcome": outcome,
        "tank_id": tank_id,
        "notes": notes,
    }
    data = {k: v for k, v in data.items() if v is not None}
    res = get_supabase().table("spawns").insert(data).execute()
    return res.data[0] if res.data else None


def get_spawns(outcome: Optional[str] = None,
               limit: int = 200) -> list[dict]:
    q = get_supabase().table("spawns").select("*")
    if outcome:
        q = q.eq("outcome", outcome)
    return q.order("pair_date", desc=True).limit(limit).execute().data


def get_spawn_by_id(spawn_id: str) -> Optional[dict]:
    res = get_supabase().table("spawns").select("*").eq("id", spawn_id).execute()
    return res.data[0] if res.data else None


def get_spawn_by_code(spawn_code: str) -> Optional[dict]:
    res = get_supabase().table("spawns").select("*").eq("spawn_code", spawn_code).execute()
    return res.data[0] if res.data else None


def update_spawn(spawn_id: str, **fields) -> Optional[dict]:
    res = get_supabase().table("spawns").update(fields).eq("id", spawn_id).execute()
    return res.data[0] if res.data else None


def delete_spawn(spawn_id: str) -> bool:
    res = get_supabase().table("spawns").delete().eq("id", spawn_id).execute()
    return bool(res.data)


# ============================================================
# FRY BATCHES
# ============================================================
def add_batch(batch_tag: str,
              spawn_id: str,
              hatch_date: Optional[str] = None,
              initial_count: int = 0,
              current_count: Optional[int] = None,
              stage: str = "fry",
              tank_id: Optional[str] = None,
              notes: Optional[str] = None) -> Optional[dict]:
    if current_count is None:
        current_count = initial_count
    data = {
        "batch_tag": batch_tag,
        "spawn_id": spawn_id,
        "hatch_date": hatch_date,
        "initial_count": initial_count,
        "current_count": current_count,
        "stage": stage,
        "tank_id": tank_id,
        "notes": notes,
    }
    res = get_supabase().table("fry_batches").insert(data).execute()
    return res.data[0] if res.data else None


def get_batches(stage: Optional[str] = None) -> list[dict]:
    q = get_supabase().table("fry_batches").select("*")
    if stage:
        q = q.eq("stage", stage)
    return q.order("created_at", desc=True).execute().data


def get_batch_by_id(batch_id: str) -> Optional[dict]:
    res = get_supabase().table("fry_batches").select("*").eq("id", batch_id).execute()
    return res.data[0] if res.data else None


def get_batch_by_tag(batch_tag: str) -> Optional[dict]:
    res = get_supabase().table("fry_batches").select("*").eq("batch_tag", batch_tag).execute()
    return res.data[0] if res.data else None


def update_batch(batch_id: str, **fields) -> Optional[dict]:
    res = get_supabase().table("fry_batches").update(fields).eq("id", batch_id).execute()
    return res.data[0] if res.data else None


def delete_batch(batch_id: str) -> bool:
    res = get_supabase().table("fry_batches").delete().eq("id", batch_id).execute()
    return bool(res.data)


# ============================================================
# PHOTOS
# ============================================================
def add_photo(entity_type: str,
              entity_id: str,
              photo_url: str,
              drive_file_id: Optional[str] = None,
              caption: Optional[str] = None,
              is_primary: bool = False,
              taken_at: Optional[str] = None) -> Optional[dict]:
    data = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "photo_url": photo_url,
        "drive_file_id": drive_file_id,
        "caption": caption,
        "is_primary": is_primary,
        "taken_at": taken_at,
    }
    data = {k: v for k, v in data.items() if v is not None}
    res = get_supabase().table("photos").insert(data).execute()
    return res.data[0] if res.data else None


def get_photos(entity_type: str, entity_id: str) -> list[dict]:
    return (get_supabase().table("photos").select("*")
            .eq("entity_type", entity_type)
            .eq("entity_id", entity_id)
            .order("created_at", desc=True).execute().data)


def get_primary_photo(entity_type: str, entity_id: str) -> Optional[dict]:
    res = (get_supabase().table("photos").select("*")
           .eq("entity_type", entity_type)
           .eq("entity_id", entity_id)
           .eq("is_primary", True)
           .limit(1).execute())
    return res.data[0] if res.data else None


def set_primary_photo(entity_type: str, entity_id: str, photo_id: str) -> bool:
    # Clear existing primary
    get_supabase().table("photos").update({"is_primary": False}) \
        .eq("entity_type", entity_type).eq("entity_id", entity_id).execute()
    # Set new primary
    res = (get_supabase().table("photos").update({"is_primary": True})
           .eq("id", photo_id).execute())
    return bool(res.data)


def delete_photo(photo_id: str) -> bool:
    res = get_supabase().table("photos").delete().eq("id", photo_id).execute()
    return bool(res.data)


# ============================================================
# EVENTS (audit log)
# ============================================================
def log_event(entity_type: str,
              entity_id: Optional[str],
              event_type: str,
              description: Optional[str] = None,
              metadata: Optional[dict] = None) -> Optional[dict]:
    data = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "event_type": event_type,
        "description": description,
        "metadata": metadata,
    }
    data = {k: v for k, v in data.items() if v is not None}
    res = get_supabase().table("events").insert(data).execute()
    return res.data[0] if res.data else None


def get_events(entity_type: Optional[str] = None,
               entity_id: Optional[str] = None,
               limit: int = 100) -> list[dict]:
    q = get_supabase().table("events").select("*")
    if entity_type:
        q = q.eq("entity_type", entity_type)
    if entity_id:
        q = q.eq("entity_id", entity_id)
    return q.order("event_date", desc=True).limit(limit).execute().data


# ============================================================
# INVENTORY
# ============================================================
def add_inventory(name: str,
                  category: Optional[str] = None,
                  quantity: float = 0,
                  unit: Optional[str] = None,
                  reorder_level: Optional[float] = None,
                  notes: Optional[str] = None) -> Optional[dict]:
    data = {
        "name": name,
        "category": category,
        "quantity": quantity,
        "unit": unit,
        "reorder_level": reorder_level,
        "notes": notes,
    }
    data = {k: v for k, v in data.items() if v is not None}
    res = get_supabase().table("inventory").insert(data).execute()
    return res.data[0] if res.data else None


def get_inventory(category: Optional[str] = None) -> list[dict]:
    q = get_supabase().table("inventory").select("*")
    if category:
        q = q.eq("category", category)
    return q.order("name").execute().data


def update_inventory(item_id: str, **fields) -> Optional[dict]:
    res = get_supabase().table("inventory").update(fields).eq("id", item_id).execute()
    return res.data[0] if res.data else None


def delete_inventory(item_id: str) -> bool:
    res = get_supabase().table("inventory").delete().eq("id", item_id).execute()
    return bool(res.data)


# ============================================================
# DASHBOARD COUNTS (for the main dashboard)
# ============================================================
def get_dashboard_counts() -> dict:
    """Return counts for the dashboard's summary cards."""
    sb = get_supabase()

    def _count(table: str, **filters) -> int:
        q = sb.table(table).select("*", count="exact")
        for k, v in filters.items():
            q = q.eq(k, v)
        res = q.execute()
        return res.count or 0

    return {
        "total_fish":       _count("fish"),
        "active_breeders":  _count("fish", stage="breeder", status="active"),
        "total_tanks":      _count("tanks"),
        "occupied_tanks":   _count("tanks", status="occupied"),
        "total_spawns":     _count("spawns"),
        "active_batches":   _count("fry_batches"),
    }
