"""
Shared helper functions used across multiple route modules.
Extracted from the original monolithic routes.py to enable code reuse
without circular dependencies.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import time
import uuid
import rapidfuzz
from rapidfuzz import process, fuzz
from app.core.database import get_db, MASTERLIST_COL, EXECUTION_INFO_COL, SNAPSHOT_COL
from app.services.validation import build_mappings
from app.services.ws_manager import manager


# ============================================================================
# NESTED KEY SETTER
# ============================================================================

def _set_nested_key(doc: Dict[str, Any], path: str, value: Any):
    """Sets a value in a nested dictionary using dot-notation path, handling lists gracefully."""
    keys = path.split(".")
    current = doc
    for key in keys[:-1]:
        if isinstance(current, list):
            if len(current) == 0:
                current.append({})
            current = current[0]
            if isinstance(current, dict):
                if key not in current:
                    current[key] = {}
                current = current[key]
        elif isinstance(current, dict):
            if key not in current:
                current[key] = {}
            current = current[key]
    
    if isinstance(current, list):
        if len(current) > 0 and isinstance(current[0], dict):
            current[0][keys[-1]] = value
    elif isinstance(current, dict):
        current[keys[-1]] = value


# ============================================================================
# BROADCAST SUMMARY (WebSocket)
# ============================================================================

async def broadcast_summary(db):
    """Calculates and broadcasts global summary counts (Status and Stages)."""
    # 1. Status Counts (Join to Snapshot)
    status_agg = [
        {"$match": {"stage": {"$exists": True}}},
        {"$lookup": {
            "from": SNAPSHOT_COL,
            "localField": "benchmarkExecutionID",
            "foreignField": "execution_id",
            "as": "snapshot"
        }},
        {"$unwind": {"path": "$snapshot", "preserveNullAndEmptyArrays": True}},
        {"$project": {
            "status": {
                "$cond": {
                    "if": {"$and": [{"$isArray": "$snapshot.data"}, {"$gt": [{"$size": "$snapshot.data"}, 0]}]},
                    "then": {"$arrayElemAt": ["$snapshot.data.standardization_status", 0]},
                    "else": "N/A"
                }
            }
        }},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}}
    ]
    
    status_counts = {"PENDING": 0, "REJECTED": 0, "ACCEPTED": 0, "ON HOLD": 0, "N/A": 0}
    async for s_doc in db[EXECUTION_INFO_COL].aggregate(status_agg):
        key = str(s_doc.get("_id") or "N/A").upper()
        if key in status_counts: status_counts[key] = s_doc["count"]
        else: status_counts["N/A"] += s_doc["count"]

    # 2. Stage Counts (Direct from ExecutionInfo with Grouping)
    stage_agg = [
        {"$match": {"stage": {"$exists": True}}},
        {"$group": {"_id": "$stage", "count": {"$sum": 1}}}
    ]
    
    # Raw counts from DB
    raw_stages = {}
    async for s_doc in db[EXECUTION_INFO_COL].aggregate(stage_agg):
        key = str(s_doc.get("_id") or "unknown").lower()
        raw_stages[key] = s_doc["count"]

    # Map to UI Groupings
    grouped_stages = {
        "VALIDATION_INITIATED": raw_stages.get("validation initiated", 0),
        "VALIDATION_IN_PROGRESS": (
            raw_stages.get("validation initiated", 0) +
            raw_stages.get("validation inprogress", 0) + 
            raw_stages.get("validation failed", 0)
        ),
        "STANDARDIZATION_IN_PROGRESS": (
            raw_stages.get("validation completed", 0) + 
            raw_stages.get("standardization inprogress", 0) + 
            raw_stages.get("standardization failed", 0)
        ),
        "STANDARDIZATION_COMPLETED": raw_stages.get("standardization completed", 0),
        "TOTAL_INVALID_RECORDS": (
            raw_stages.get("validation initiated", 0) +
            raw_stages.get("validation inprogress", 0) + 
            raw_stages.get("validation completed", 0) + 
            raw_stages.get("validation failed", 0) +
            raw_stages.get("standardization inprogress", 0) + 
            raw_stages.get("standardization failed", 0)
        )
    }

    # Broadcast to all clients (Combined with Pipeline update type)
    await manager.broadcast({
        "type": "PIPELINE_UPDATE",
        "summary": {
            **status_counts,
            **grouped_stages
        }
    })


# ============================================================================
# DUPLICATE CHECKER
# ============================================================================

async def _check_duplicate(db, type_name, value, metadata_filters: Dict[str, Any] = None):
    """Checks if a record with the same type and value (and optional metadata) already exists."""
    query = {"type": type_name, "data.value": value}
    if metadata_filters:
        for k, v in metadata_filters.items():
            query[f"data.metadata.{k}"] = v
    return await db[MASTERLIST_COL].find_one(query)


# ============================================================================
# BASE MASTERLIST DOCUMENT BUILDER
# ============================================================================

def _build_base_ml_doc(type_name, data_content, updated_by: str = "", execution_id: str = None):
    """Builds the common base structure for a 'In Review' masterlist document with data before history."""
    now = datetime.utcnow()
    doc = {
        "`_id`": str(uuid.uuid4()),
        "type": type_name,
        "status": "Draft",
        "data": data_content,
        "history": {
            "updatedOn": now.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "updatedBy": updated_by or "xxx@amd.com",
            "to": None,
            "valueField": None
        }
    }
    if execution_id:
        doc["execution_id"] = execution_id
    return doc


# ============================================================================
# MASTERLIST MAPPINGS
# ============================================================================

async def get_masterlist_mappings(field_type: str):
    """
    Retrieves the mapping structure for a given masterlist type (e.g., CPUModel, instanceType).
    Returns mapping paths for the primary value and any nested metadata fields.
    """
    db = get_db()
    doc = await db[MASTERLIST_COL].find_one({"type": field_type, "status": "Published"})
    if not doc:
        return {}
    
    data = doc.get("data", {})
    metadata = data.get("metadata", {})
    
    # Correctly parse mapping_X fields from the metadata object
    meta_mappings = {k.replace("mapping_", ""): v for k, v in metadata.items() if k.startswith("mapping_")}
    
    return {
        "mapping": data.get("mapping"),
        "metadata_mappings": meta_mappings
    }


# ============================================================================
# DYNAMIC FIELD MAP (Discovery Cache)
# ============================================================================

# Global in-memory cache for expensive dashboard queries
_report_cache = {
    "total_invalid": {"value": None, "updated_at": 0},
    "counts_metrics": {"value": None, "updated_at": 0},
    "summary_counts": {"value": None, "updated_at": 0}
}
_discovery_cache = {"field_map": None, "updated_at": 0}
CACHE_TTL = 300  # 5 minutes

async def _get_dynamic_field_map(db) -> Dict[str, Dict[str, Any]]:
    """
    Scans the masterlist to build a map of every field name (primary or metadata)
    to its actual database location and the record type it belongs to.
    """
    now = time.time()
    if _discovery_cache["field_map"] and (now - _discovery_cache["updated_at"] < CACHE_TTL):
        return _discovery_cache["field_map"]
        
    field_map = {}
    all_types = await db[MASTERLIST_COL].distinct("type", {"status": "Published"})
    
    for t in all_types:
        sample = await db[MASTERLIST_COL].find_one({"type": t, "status": "Published"})
        if not sample: continue
        
        data = sample.get("data", {})
        # 1. Primary field mapping (the unique 'value' of this type)
        t_norm = t.lower()
        # Always prioritize primary definitions
        field_map[t_norm] = {"type": t, "path": "data.value", "is_primary": True}
            
        # 2. Metadata fields
        metadata = data.get("metadata", {})
        if isinstance(metadata, dict):
            for k in metadata.keys():
                if k.startswith("mapping_"): continue
                k_norm = k.lower()
                # Do NOT overwrite a primary definition with a metadata location
                if k_norm not in field_map or not field_map[k_norm]["is_primary"]:
                    field_map[k_norm] = {"type": t, "path": f"data.metadata.{k}", "is_primary": False}
                
    _discovery_cache["field_map"] = field_map
    _discovery_cache["updated_at"] = now
    return field_map


# ============================================================================
# DYNAMIC DRAFT FIELD SCHEMA
# ============================================================================

async def get_dynamic_draft_fields(type_name: str) -> Dict[str, Any]:
    """
    Dynamically discovers the schema for a masterlist type by inspecting published records.
    """
    db = get_db()
    
    # 1. Resolve actual type name (case-insensitive)
    all_types = await db[MASTERLIST_COL].distinct("type")
    actual_type = type_name
    for t in all_types:
        if t.lower() == type_name.lower():
            actual_type = t
            break
            
    # 2. Find a representative published record to use as a template
    template = await db[MASTERLIST_COL].find_one({"type": actual_type, "status": "Published"})
    if not template:
        # Fallback to any record if no published one exists
        template = await db[MASTERLIST_COL].find_one({"type": actual_type})
        
    if not template:
        return {
            "actual_type": actual_type,
            "mapping": "",
            "metadata_fields": ["value"],
            "metadata_mappings": {},
            "field_types": {"value": "string"}
        }
        
    data = template.get("data", {})
    metadata = data.get("metadata", {})
    
    meta_fields = []
    meta_mappings = {}
    
    if isinstance(metadata, dict):
        for k, v in metadata.items():
            if k.startswith("mapping_"):
                field_name = k.replace("mapping_", "")
                meta_mappings[field_name] = v
            else:
                meta_fields.append(k)
                
    # Ensure all meta_fields have a mapping in the mappings dict (even if empty)
    for f in meta_fields:
        if f not in meta_mappings:
            meta_mappings[f] = metadata.get(f"mapping_{f}", "")

    # 3. Detect Datatypes for all discovered fields
    all_target_fields = ["value"] + meta_fields
    
    # Track sets of Python types encountered for each field
    field_actual_types = {f: set() for f in all_target_fields}
    
    sample_cursor = db[MASTERLIST_COL].find({"type": actual_type, "status": "Published"}).limit(10)
    async for sample_doc in sample_cursor:
        s_data = sample_doc.get("data", {})
        s_meta = s_data.get("metadata", {})
        
        for f in all_target_fields:
            val = s_data.get("value") if f == "value" else s_meta.get(f)
            
            # Record type if value is not effectively empty
            if val is not None and str(val).strip() != "":
                field_actual_types[f].add(type(val))
                    
    # Finalize types based on encountered Python classes
    field_types = {}
    for f in all_target_fields:
        types = field_actual_types[f]
        if not types:
            field_types[f] = "string" # Default
        elif str in types:
            field_types[f] = "string" # If it's a string in DB, it's 'string'
        elif int in types or float in types:
            field_types[f] = "integer" # If it's pure numeric in DB, it's 'integer'
        else:
            field_types[f] = "string"
                    
    return {
        "actual_type": actual_type,
        "mapping": data.get("mapping", ""),
        "sutType": data.get("sutType"),
        "mapping_sutType": data.get("mapping_sutType"),
        "metadata_fields": all_target_fields,
        "metadata_mappings": meta_mappings,
        "field_types": field_types
    }


# ============================================================================
# AGE COUNTS
# ============================================================================

async def get_dynamic_age_counts(db, base_query: Dict[str, Any]):
    """
    Calculates the distribution of records across age buckets (Green, Yellow, Red)
    using the ExecutionInfo collection's lastModifiedOn field for consistency.
    """
    counts = {"red": 0, "yellow": 0, "green": 0}
    now = datetime.utcnow()
    
    count_agg = [
        {"$match": {**base_query, "lastModifiedOn": {"$type": "string"}}},
        {"$addFields": {
            "now": now,
            "dt": {"$dateFromString": {"dateString": "$lastModifiedOn", "onError": None}}
        }},
        {"$match": {"dt": {"$ne": None}}},
        {"$addFields": {
            "diffDays": {
                "$floor": {
                    "$divide": [{"$subtract": ["$now", "$dt"]}, 86400000]
                }
            }
        }},
        {"$group": {
            "_id": {
                "$cond": [
                    {"$lt": ["$diffDays", 3]}, "green",
                    {"$cond": [{"$lt": ["$diffDays", 6]}, "yellow", "red"]}
                ]
            },
            "count": {"$sum": 1}
        }}
    ]

    async for result_doc in db[EXECUTION_INFO_COL].aggregate(count_agg):
        if result_doc["_id"] in counts:
            counts[result_doc["_id"]] = result_doc["count"]
    
    return counts


# ============================================================================
# FUZZY BENCHMARK RESOLVER
# ============================================================================

async def get_masterlist_values(field_type: str) -> List[str]:
    """Helper to fetch unique published values for a masterlist type."""
    db = get_db()
    values = await db[MASTERLIST_COL].distinct("data.value", {"type": field_type, "status": "Published"})
    return [str(v) for v in values if v]

async def resolve_fuzzy_benchmarks(benchmarkType: Optional[str] = None, benchmarkCategory: Optional[str] = None) -> Dict[str, Any]:
    """Helper to resolve fuzzy benchmark terms into exact masterlist values."""
    db = get_db()
    resolved = {}
    
    # Fetch valid types and categories
    valid_types = await db[MASTERLIST_COL].distinct("data.value", {"type": "benchmarkType", "status": "Published"})
    valid_types = [str(t) for t in valid_types if t]
    type_map = {t.lower(): t for t in valid_types}
    
    valid_cats = await db[MASTERLIST_COL].distinct("data.metadata.benchmarkCategory")
    valid_cats = [str(c) for c in valid_cats if c]
    cat_map = {c.lower(): c for c in valid_cats}
    
    # Exact category match check
    term_lower = (benchmarkCategory or "").lower().strip()
    if term_lower in cat_map:
        resolved["benchmarkCategory"] = cat_map[term_lower]
        resolved["benchmarkCategory_is_fuzzy"] = False
        return resolved

    # Exact type match check
    type_term_lower = (benchmarkType or "").lower().strip()
    if type_term_lower in type_map:
        resolved["benchmarkType"] = type_map[type_term_lower]
        resolved["benchmarkType_is_fuzzy"] = False
        return resolved

    if benchmarkType:
        match_res = process.extractOne(benchmarkType.lower(), type_map.keys(), scorer=fuzz.partial_ratio, score_cutoff=60)
        if match_res:
            match_str = match_res[0]
            # Safety check: prevent short matching on 'lm' / 'llm' resulting in 'dlrm'
            if benchmarkType.lower() in ["lm", "llm", "ai-llm"] and match_str == "dlrm":
                resolved["benchmarkType"] = benchmarkType
                resolved["benchmarkType_is_fuzzy"] = False
            else:
                resolved["benchmarkType"] = type_map[match_str]
                resolved["benchmarkType_is_fuzzy"] = True
        else:
            resolved["benchmarkType"] = benchmarkType
            resolved["benchmarkType_is_fuzzy"] = False

    if benchmarkCategory:
        match_res = process.extractOne(benchmarkCategory.lower(), cat_map.keys(), scorer=fuzz.partial_ratio, score_cutoff=60)
        if match_res:
            match_str = match_res[0]
            resolved["benchmarkCategory"] = cat_map[match_str]
            resolved["benchmarkCategory_is_fuzzy"] = True
        else:
            resolved["benchmarkCategory"] = benchmarkCategory
            resolved["benchmarkCategory_is_fuzzy"] = False
    
    return resolved


# ============================================================================
# ALL UNIQUE VALUES
# ============================================================================

async def _get_masterlist_all_unique_values(db):
    """
    Helper to fetch all published unique values for all supported parameters (including metadata).
    Now fully dynamic: uses the discovered field map to locate values.
    """
    field_map = await _get_dynamic_field_map(db)
    mappings = await build_mappings()
    
    # We want to return unique values for every field mentioned in our mappings
    all_params = list(mappings.keys())
    
    unique_data = {}
    for param in all_params:
        param_norm = param.lower()
        info = field_map.get(param_norm)
        
        if info:
            # Use the discovered path (Primary 'data.value' or Metadata 'data.metadata.X')
            values = await db[MASTERLIST_COL].distinct(info["path"], {"type": info["type"], "status": "Published"})
        else:
            # Fallback: try to guess the path if not in the map
            values = await db[MASTERLIST_COL].distinct(f"data.metadata.{param}", {"status": "Published"})
            
        # Normalize to string and strip to remove duplicates like 128 and "128" or trailing spaces
        unique_data[param] = sorted(list(set(str(v).strip() for v in values if v is not None)))
    
    return unique_data


# ============================================================================
# RBAC SECURITY & WORKLOAD AUTO-ASSIGNMENT HELPERS
# ============================================================================

SECRET_KEY = "super-secret-key-for-data-hygiene"
ALGORITHM = "HS256"

from fastapi import Request, HTTPException, Depends
import jwt

async def build_expertise_query_filter(expert_cats: list, db, username: Optional[str] = None, assigned_only: bool = False) -> dict:
    """
    Builds a MongoDB query filter for Executioninfo records strictly based on raw benchmarkCategory.
    If assigned_only is True, filters to records assigned to the specified user.
    """
    if not expert_cats:
        return {}
        
    or_conditions = []
    for cat in expert_cats:
        if not cat:
            continue
        cat_str = str(cat).strip()
        cat_regex = {"$regex": f"^{cat_str}$", "$options": "i"}
        
        # Strictly direct match on raw benchmarkCategory in the execution records
        cond = {"benchmarkCategory": cat_regex}
        if assigned_only and username:
            cond["assignment.assigned_sme"] = username
        or_conditions.append(cond)
            
    if or_conditions:
        return {"$or": or_conditions}
    return {}

def get_current_user(request: Request) -> dict:
    """
    Decodes the JWT token from the Authorization header to extract user claims.
    Falls back to a default 'tester' SME user if no Authorization header is present
    to ensure full backward compatibility with local scripts and unauthenticated requests.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        # Fallback to default user to avoid breaking legacy/unauthenticated requests
        return {
            "username": "tester",
            "role": "SME",
            "expertise": ["OSS", "Database", "Cloud"],
            "benchmarkCategories": ["OSS", "Database", "Cloud"]
        }
        
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return {
            "username": payload.get("sub"),
            "role": payload.get("role", "SME"),
            "expertise": payload.get("benchmarkCategories", payload.get("expertise", [])),
            "benchmarkCategories": payload.get("benchmarkCategories", payload.get("expertise", []))
        }
    except Exception:
        raise HTTPException(status_code=401, detail="Session expired or invalid signature")


async def auto_assign_records(db, record_ids):
    """
    Automatically assigns records to the least-loaded respective active SMEs and Admins based on benchmarkCategory expertise.
    If no specialized SME/Admin is found, it remains unassigned.
    Optimized: Employs in-memory workload caching to distribute large uploaded batches (e.g., 400 records) instantly and equally.
    """
    # Pre-cache all active SMEs and Admins (case-insensitive roles)
    users_cursor = db["users"].find({"role": {"$in": ["SME", "Admin", "ADMIN", "sme"]}, "status": "Active"})
    all_users = await users_cursor.to_list(length=100)
    
    if not all_users:
        print("No active SMEs or Admins found for automatic assignment.")
        return

    # Fetch initial workload for all active users once (extremely fast)
    user_workloads = {}
    for u in all_users:
        assignee_id = u.get("email") or u.get("username")
        load = await db[EXECUTION_INFO_COL].count_documents({
            "$or": [
                {"tester": assignee_id},
                {"assignment.assigned_sme": assignee_id}
            ],
            "stage": {"$ne": "standardization completed"}
        })
        user_workloads[assignee_id] = load

    # Fetch all records to assign
    cursor = db[EXECUTION_INFO_COL].find({"_id": {"$in": record_ids}})
    records = await cursor.to_list(length=len(record_ids))
    
    for rec in records:
        category = rec.get("benchmarkCategory")
        if not category:
            continue
            
        # Find active users expert in this category (case-insensitive)
        eligible_users = []
        for u in all_users:
            expert_list = [str(x).strip().lower() for x in u.get("benchmarkCategories", u.get("expertise", []))]
            if category.lower() in expert_list:
                eligible_users.append(u)
                
        if not eligible_users:
            print(f"No eligible SMEs or Admins found for category '{category}' for record {rec.get('benchmarkExecutionID')}")
            continue
            
        # Find the least loaded eligible user using in-memory loads
        least_loaded_user = None
        min_load = float("inf")
        
        for u in eligible_users:
            assignee_id = u.get("email") or u.get("username")
            load = user_workloads.get(assignee_id, 0)
            if load < min_load:
                min_load = load
                least_loaded_user = assignee_id
                
        if least_loaded_user:
            # Increment workload in-memory so subsequent iterations see this assignment immediately
            user_workloads[least_loaded_user] += 1
            
            print(f"Auto-assigning record {rec.get('benchmarkExecutionID')} to user: {least_loaded_user} (In-Memory Load: {min_load})")
            
            # Assign to the selected least-loaded user in the DB
            await db[EXECUTION_INFO_COL].update_one(
                {"_id": rec["_id"]},
                {"$set": {
                    "tester": least_loaded_user,  # Standardized to use email as tester
                    "assignment": {
                        "status": "ASSIGNED",
                        "assigned_sme": least_loaded_user,
                        "assigned_at": datetime.utcnow().isoformat(),
                        "proposals": [],
                        "feedback": None
                    }
                }}
            )
