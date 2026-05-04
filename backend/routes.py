from fastapi import APIRouter, Query, Body, HTTPException, File, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from typing import List, Dict, Any, Optional
import time
import json
import rapidfuzz
from rapidfuzz import process
from datetime import datetime, timedelta
import uuid
import os
import asyncio
from database import get_db, MASTERLIST_COL, EXECUTION_INFO_COL, SNAPSHOT_COL
from validation import build_mappings, get_validator
from utils import get_nested_value, get_metadata_schema
from ws_manager import manager
from trigger import get_current_summary

router = APIRouter()
 
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



class ApproveSuggestionRequest(BaseModel):
    model_config = ConfigDict(
        extra='allow',
        json_schema_extra={
            "example": {
                "execution_id": "uuid-12345",
                "field_name": "CPUModel",
                "accepted_value": "9575F",
                "currentStatus": "Accepted",
                "coreCount": "128",
                "masterlist_id": "67b97e9de296d92efb1bd7e4",
                "metadata": {
                    "Architecture": "x86-64",
                    "CCDCount": "16",
                    "CPU(s)": "128",
                    "CPUMaxMHz": "3700",
                    "Core(s)PerSocket": "64",
                    "CorePerCCD": "8",
                    "Family": "Turin",
                    "L3Cache": "512 MB",
                    "L3CacheInstances": "16",
                    "Microarchitecture": "Zen 5",
                    "Microcode": "0x1000000",
                    "Model": "9575F",
                    "PeakPerformance": "High",
                    "Socket(s)": "1",
                    "Technology": "4nm",
                    "Thread(s)PerCore": "2",
                    "num_L3": "16",
                    "cloudProvider": "AWS",
                    "BenchmarkType": "Nginx",
                    "BenchmarkCategory": "Web",
                    "sutType": "Server"
                }
            }
        }
    )
 
    execution_id: str
    field_name: str
    accepted_value: str
    currentStatus: str = "Accepted"
    coreCount: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
class BatchExecutionRequest(BaseModel):
    execution_ids: List[str]

class RejectRecordRequest(BaseModel):
    execution_id: str
    currentStatus: str = "L0 Data"

class DraftRecordRequest(BaseModel):
    model_config = ConfigDict(extra='allow')

    value: str
    currentStatus: str = "ON HOLD"
    id: Optional[str] = None
    execution_id: Optional[str] = None
    # Dynamic metadata container
    metadata: Dict[str, Any] = {}
    
    # Keeping named fields for backward compatibility and convenience
    family: Optional[str] = ""
    corecount: Optional[str] = ""
    cpumodel: Optional[str] = ""
    cloudprovider: Optional[str] = ""
    benchmarktype: Optional[str] = ""

    def get_merged_metadata(self) -> Dict[str, Any]:
        """Merges named fields and the generic metadata dict, including extra fields."""
        data = dict(self.metadata)
        
        # Capture all extra fields sent from the UI (e.g. 'Family', 'CPU(s)')
        if hasattr(self, 'model_extra') and self.model_extra:
            data.update(self.model_extra)

        # Only add named fields if they aren't already in the metadata dict and aren't empty
        if self.family and "Family" not in data: data["Family"] = self.family
        if self.corecount and "coreCount" not in data: data["coreCount"] = self.corecount
        if self.cpumodel and "CPUModel" not in data: data["CPUModel"] = self.cpumodel
        if self.cloudprovider and "cloudProvider" not in data: data["cloudProvider"] = self.cloudprovider
        if self.benchmarktype and "BenchmarkType" not in data: data["BenchmarkType"] = self.benchmarktype
        return data

# Internal Helpers for Draft Workflows
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

async def _check_duplicate(db, type_name, value, metadata_filters: Dict[str, Any] = None):
    """Checks if a record with the same type and value (and optional metadata) already exists."""
    query = {"type": type_name, "data.value": value}
    if metadata_filters:
        for k, v in metadata_filters.items():
            query[f"data.metadata.{k}"] = v
    return await db[MASTERLIST_COL].find_one(query)

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
    import time
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

async def get_dynamic_draft_fields(type_name: str) -> Dict[str, Any]:
    """
    Dynamically discovers the schema for a masterlist type by inspecting published records.
    Returns: {
        "actual_type": "CPUModel", 
        "mapping": "...", 
        "sutType": "...", 
        "mapping_sutType": "...",
        "metadata_fields": ["Family", "coreCount"],
        "metadata_mappings": {"Family": "...", "coreCount": "..."}
    }
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
    # We scan a sample of up to 10 published records of this type to determine native DB types.
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

@router.get("/invalid-summary")
async def get_invalid_summary(
    search: Optional[str] = Query(None, description="Search by Execution ID, Benchmark Type, or Category"),
    status: Optional[str] = Query(None, description="Filter by business status: PENDING, REJECTED, ACCEPTED, 'On Hold'"),
    stage: Optional[str] = Query(None, description="Filter by pipeline stage: VALIDATION_INPROGRESS, STANDARDIZATION_COMPLETED, etc."),
    age: Optional[str] = Query(None, description="Filter by age: green, yellow, or red"),
    page: int = Query(1, ge=1), 
    size: int = Query(50, ge=1, le=500)
):
    """
    Returns strictly the Execution_id and the names of the specific fields that are invalid.
    Optimized: Now queries the 'snapshot' collection directly for sub-second performance.
    """
    db = get_db()
    
    # 1. Search Filter (applies to all queries)
    search_query = {}
    if search:
        # Optimization: If search looks like a full UUID, do an exact match first (super fast)
        is_uuid = len(search) == 36 and search.count("-") == 4
        
        if is_uuid:
            search_query["benchmarkExecutionID"] = search
        else:
            search_regex = {"$regex": search, "$options": "i"}
            resolved = await resolve_fuzzy_benchmarks(benchmarkType=search, benchmarkCategory=search)
            or_filters = [{"benchmarkExecutionID": search_regex}]
           
            if "benchmarkType" in resolved:
                if resolved.get("benchmarkType_is_fuzzy"):
                    or_filters.append({"benchmarkType": resolved["benchmarkType"]})
                else:
                    or_filters.append({"benchmarkType": search_regex})
           
            if "benchmarkCategory" in resolved:
                if resolved.get("benchmarkCategory_is_fuzzy"):
                    or_filters.append({"benchmarkCategory": resolved["benchmarkCategory"]})
                else:
                    or_filters.append({"benchmarkCategory": search_regex})
                   
            if len(or_filters) == 1:
                or_filters.extend([
                    {"benchmarkType": search_regex},
                    {"benchmarkCategory": search_regex}
                ])
               
            search_query["$or"] = or_filters

    # 4. Business Status Pre-Fetch Filter (Replaces heavy $lookup)
    status_condition = {}
    if status:
        status_list = [s.strip().upper() for s in status.split(",")]
        other_statuses = [s for s in status_list if s not in ["PENDING", "N/A"]]
        
        snapshot_query = {}
        if other_statuses and "PENDING" in status_list:
            snapshot_query = {"$or": [
                {"data.0.standardization_status": {"$in": other_statuses}},
                {"data.0.standardization_status": "PENDING"},
                {"data.0.standardization_status": {"$exists": False}}
            ]}
        elif other_statuses:
            snapshot_query = {"data.0.standardization_status": {"$in": other_statuses}}
        elif "PENDING" in status_list:
             snapshot_query = {"$or": [
                {"data.0.standardization_status": "PENDING"},
                {"data.0.standardization_status": {"$exists": False}}
            ]}
            
        status_exec_ids = []
        if snapshot_query:
            # Quick collection scan/index scan to extract just the IDs (milliseconds instead of seconds)
            cursor = db[SNAPSHOT_COL].find(snapshot_query, {"execution_id": 1})
            status_exec_ids = [doc["execution_id"] for doc in await cursor.to_list(None)]
            
        or_conditions = []
        if "N/A" in status_list:
            # N/A covers any stage that isn't finished
            or_conditions.append({"stage": {"$ne": "standardization completed"}})
            
        if status_exec_ids:
            # PENDING and other statuses are resolved via snapshot execution IDs
            or_conditions.append({"benchmarkExecutionID": {"$in": status_exec_ids}, "stage": "standardization completed"})
            
        if len(or_conditions) > 1:
            status_condition = {"$or": or_conditions}
        elif len(or_conditions) == 1:
            status_condition = or_conditions[0]
        else:
            # If they queried PENDING or other statuses but 0 IDs were found, force a mismatch
            status_condition = {"_id": "force_empty_result_status_not_found"}

    if age:
        now = datetime.utcnow()
        green_threshold = (now - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        yellow_threshold = (now - timedelta(days=6)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        if age.lower() == "green":
            search_query["lastModifiedOn"] = {"$gte": green_threshold}
        elif age.lower() == "yellow":
            search_query["lastModifiedOn"] = {"$lt": green_threshold, "$gte": yellow_threshold}
        elif age.lower() == "red":
            search_query["lastModifiedOn"] = {"$lt": yellow_threshold}

    # 6. Final Match Query (Include Invalid, In-Progress, and Accepted records for visibility)
    # We now show everything that has at least reached the validation stage
    base_match = {"stage": {"$exists": True}}
    
    # 6. Final Match Query
    match_query = {"stage": {"$exists": True}}
    
    if search_query:
        # Merge search filters into the match_query
        match_query.update(search_query)
        
    stage_condition = {}
    if stage:
        # Normalize: lower case, replace hyphens and underscores with spaces, and handle 'inprogress' vs 'in progress'
        stage_list = [s.strip().lower().replace("_", " ").replace("-", " ").replace("in progress", "inprogress") for s in stage.split(",")]
        
        # UI mapping fix: include failed queues and initiated in the 'inprogress' groups
        if "validation inprogress" in stage_list:
            if "validation failed" not in stage_list:
                stage_list.append("validation failed")
            if "validation initiated" not in stage_list:
                stage_list.append("validation initiated")
            
        if "standardization inprogress" in stage_list:
            if "standardization failed" not in stage_list:
                stage_list.append("standardization failed")
            if "validation completed" not in stage_list:
                stage_list.append("validation completed")
            
        if len(stage_list) > 1:
            stage_condition = {"stage": {"$in": stage_list}}
        else:
            stage_condition = {"stage": stage_list[0]}
            
    # Combine everything into the final match query BEFORE lookup
    # Stage + Status use $or (union) because they target mutually exclusive stage values
    # Search uses $and (intersection) to narrow results
    if stage_condition and status_condition:
        # Union: show records matching EITHER the stage OR the status
        combined = {"$or": [stage_condition, status_condition]}
        match_query = {"$and": [match_query, combined]}
    elif stage_condition:
        match_query = {"$and": [match_query, stage_condition]}
    elif status_condition:
        match_query = {"$and": [match_query, status_condition]}
    # else match_query stays as-is
        
    print(f"API Executing Final Match Query: {match_query}")

    skip_count = (page - 1) * size
    
    # 2. Extract Data (Use ExecutionInfo as base for pipeline visibility)
    # Optimized: $lookup only fetches the fields we need from snapshot
    data_pipeline = [
        {"$match": match_query},
        # Priority sort: active pipeline records on top, then by recency
        {"$addFields": {
            "_sortPriority": {
                "$switch": {
                    "branches": [
                        {"case": {"$eq": ["$stage", "validation initiated"]}, "then": 0},
                        {"case": {"$eq": ["$stage", "validation inprogress"]}, "then": 1},
                        {"case": {"$eq": ["$stage", "standardization inprogress"]}, "then": 2},
                        {"case": {"$eq": ["$stage", "validation completed"]}, "then": 3}
                    ],
                    "default": 4
                }
            }
        }},
        {"$sort": {"_sortPriority": 1, "lastModifiedOn": -1}},
        {"$skip": skip_count},
        {"$limit": size},
        {"$lookup": {
            "from": SNAPSHOT_COL,
            "localField": "benchmarkExecutionID",
            "foreignField": "execution_id",
            "pipeline": [{"$project": {
                "data.standardization_status": 1,
                "data.invalidValues.field": 1,
                "data.invalidValues.comparingData": 1,
                "data.invalidValues.validation_status": 1,
                "data.invalidValues.metadata.name": 1,
                "data.invalidValues.metadata.validation_status": 1,
                "data.invalidValues.metadata.comparingData": 1
            }}],
            "as": "snapshot"
        }},
        {"$unwind": {"path": "$snapshot", "preserveNullAndEmptyArrays": True}}
    ]
    
    # 3. Run data fetch and count in parallel for speed
    # Run ALL queries in parallel for maximum speed
    async def _fetch_data():
        records = []
        async for doc in db[EXECUTION_INFO_COL].aggregate(data_pipeline):
            snapshot = doc.get("snapshot") or {}
            snapshot_data = (snapshot.get("data") or [{}])[0]
            
            invalid_fields = []
            if snapshot_data.get("invalidValues"):
                invalid_fields = sorted(list(set(
                    [p.get("field") for p in snapshot_data.get("invalidValues", []) if p.get("validation_status") == "invalid"] +
                    [m.get("name") for p in snapshot_data.get("invalidValues", []) for m in p.get("metadata", []) if m.get("validation_status") == "invalid"]
                )))
            else:
                invalid_fields = doc.get("invalidFields") or []
                
            doc_stage = str(doc.get("stage", "validation inprogress")).lower()
            if doc_stage == "standardization completed":
                status_val = snapshot_data.get("standardization_status", "PENDING")
            else:
                status_val = "N/A"
                
            records.append({
                "ExecutionId": doc.get("benchmarkExecutionID"),
                "Status": status_val,
                "Stage": doc.get("stage", "validation inprogress"),
                "BenchmarkType": doc.get("benchmarkType", "N/A"),
                "BenchmarkCategory": doc.get("benchmarkCategory", "N/A"),
                "InvalidFields": invalid_fields,
                "suggestionsCount": any(
                    len(p.get("comparingData", [])) > 0 or 
                    any(len(m.get("comparingData", [])) > 0 for m in p.get("metadata", []))
                    for p in snapshot_data.get("invalidValues", [])
                ),
                "updatedOn": doc.get("lastModifiedOn")
            })
        return records

    async def _fetch_count():
        if search or status or stage or age:
            count_pipeline = [{"$match": match_query}, {"$count": "total"}]
            count_result = await db[EXECUTION_INFO_COL].aggregate(count_pipeline).to_list(1)
            return count_result[0]["total"] if count_result else 0
        else:
            return await db[EXECUTION_INFO_COL].count_documents(match_query)

    async def _fetch_age_counts():
        if not search_query:
            import trigger
            _cached = trigger._LAST_SUMMARY
            return {"red": _cached.get("red", 0), "yellow": _cached.get("yellow", 0), "green": _cached.get("green", 0)}
        else:
            age_search_query = {}
            is_uuid = len(search) == 36 and search.count("-") == 4
            if is_uuid: age_search_query["benchmarkExecutionID"] = search
            else: age_search_query["benchmarkExecutionID"] = {"$regex": search, "$options": "i"}
            return await get_dynamic_age_counts(db, age_search_query)

    async def _fetch_stage_counts():
        stage_agg = await db[EXECUTION_INFO_COL].aggregate([
            {"$match": {"stage": {"$exists": True}}},
            {"$group": {"_id": "$stage", "count": {"$sum": 1}}}
        ]).to_list(20)
        raw_stages = {str(s["_id"] or "unknown").lower(): s["count"] for s in stage_agg}
        return {
            "VALIDATION_INITIATED": raw_stages.get("validation initiated", 0),
            "VALIDATION_IN_PROGRESS": (
                raw_stages.get("validation inprogress", 0) +
                raw_stages.get("validation failed", 0)
            ),
            "VALIDATION_COMPLETED": raw_stages.get("validation completed", 0),
            "STANDARDIZATION_IN_PROGRESS": (
                raw_stages.get("standardization inprogress", 0) +
                raw_stages.get("standardization failed", 0)
            ),
            "STANDARDIZATION_COMPLETED": raw_stages.get("standardization completed", 0),
        }


    async def _fetch_status_counts():
        # Query Snapshot collection DIRECTLY - no expensive $lookup needed
        status_results = await db[SNAPSHOT_COL].aggregate([
            {"$project": {
                "status": {
                    "$cond": {
                        "if": {"$and": [{"$isArray": "$data"}, {"$gt": [{"$size": "$data"}, 0]}]},
                        "then": {"$arrayElemAt": ["$data.standardization_status", 0]},
                        "else": "PENDING"
                    }
                }
            }},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}}
        ]).to_list(20)
        counts = {"PENDING": 0, "REJECTED": 0, "ACCEPTED": 0, "ON HOLD": 0, "N/A": 0}
        for s in status_results:
            key = str(s["_id"] or "N/A").upper()
            if key in counts: counts[key] = s["count"]
            else: counts["N/A"] += s["count"]
        return counts

    # Execute ALL 5 queries in parallel
    invalid_records, total_records, summary_counts, grouped_stages, status_counts = await asyncio.gather(
        _fetch_data(), _fetch_count(), _fetch_age_counts(), _fetch_stage_counts(), _fetch_status_counts()
    )

    try:
        return {
            "status": "success",
            "total_invalid_records": total_records,
            "page": page,
            "size": size,
            "returned_records": len(invalid_records),
            "summary": {
                **summary_counts,
                **status_counts,
                **grouped_stages
            },
            "data": invalid_records
        }
    except Exception as e:
        print(f"DEBUG ERROR in get_invalid_summary: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

@router.get("/summary-poll")
async def get_summary_poll():
    """
    Fallback endpoint for environments where WebSockets are blocked.
    Returns the same flattened summary structure as the WebSocket broadcast.
    """
    db = get_db()
    summary_data = await get_current_summary(db)
    return {
        "status": "success",
        "summary": summary_data
    }

@router.post("/invalid-summary/batch")
async def get_invalid_summary_batch(request: BatchExecutionRequest):
    """
    Returns summarized statistics for a batch of execution IDs.
    """
    try:
        db = get_db()
        execution_ids = request.execution_ids
        
        if not execution_ids:
            return {
                "status": "success",
                "total_invalid_records": 0,
                "summary": {"red": 0, "yellow": 0, "green": 0, "PENDING": 0, "REJECTED": 0, "ACCEPTED": 0, "ON HOLD": 0, "N/A": 0},
                "data": []
            }

        # 1. Base Match
        match_query = {"benchmarkExecutionID": {"$in": execution_ids}}
        
        # 3. Aggregation Pipeline
        pipeline = [
            {"$match": match_query},
            # Deduplicate by benchmarkExecutionID picking the latest record
            {"$sort": {"lastModifiedOn": -1}},
            {"$group": {
                "_id": "$benchmarkExecutionID",
                "doc": {"$first": "$$ROOT"}
            }},
            {"$replaceRoot": {"newRoot": "$doc"}},
            {"$lookup": {
                "from": SNAPSHOT_COL,
                "localField": "benchmarkExecutionID",
                "foreignField": "execution_id",
                "as": "snapshot"
            }},
            {"$unwind": {"path": "$snapshot", "preserveNullAndEmptyArrays": True}}
        ]

        cursor = db[EXECUTION_INFO_COL].aggregate(pipeline)
        
        invalid_records = []
        async for doc in cursor:
            # Yield control so background processes are not starved!
            await asyncio.sleep(0)
            
            snapshot = doc.get("snapshot") or {}
            snapshot_data = (snapshot.get("data") or [{}])[0]
            
            # Always derive invalid fields from the snapshot to ensure metadata fields are included
            invalid_fields = []
            if snapshot_data.get("invalidValues"):
                invalid_fields = sorted(list(set(
                    [p.get("field") for p in snapshot_data.get("invalidValues", []) if p.get("validation_status") == "invalid"] +
                    [m.get("name") for p in snapshot_data.get("invalidValues", []) for m in p.get("metadata", []) if m.get("validation_status") == "invalid"]
                )))
            else:
                # Fallback to ExecutionInfo cache if snapshot is missing
                invalid_fields = doc.get("invalidFields") or []
            
            # Calculate Status based on Stage
            stage = str(doc.get("stage", "validation inprogress")).lower()
            if stage == "standardization completed":
                status_val = snapshot_data.get("standardization_status", "PENDING")
            else:
                status_val = "N/A"

            record = {
                "ExecutionId": doc.get("benchmarkExecutionID"),
                "Status": status_val,
                "Stage": doc.get("stage", "validation inprogress"),
                "BenchmarkType": doc.get("benchmarkType", "N/A"),
                "BenchmarkCategory": doc.get("benchmarkCategory", "N/A"),
                "InvalidFields": invalid_fields or [],
                "suggestionsCount": bool(snapshot_data.get("invalidValues")),
                "updatedOn": doc.get("lastModifiedOn")
            }
            invalid_records.append(record)

        # 3. Summary Counts (Limited to the requested IDs)
        summary_counts = await get_dynamic_age_counts(db, {"execution_id": {"$in": execution_ids}})
        
        status_agg = [
            {"$match": match_query},
            {"$lookup": {
                "from": SNAPSHOT_COL,
                "localField": "benchmarkExecutionID",
                "foreignField": "execution_id",
                "as": "snapshot"
            }},
            {"$unwind": {"path": "$snapshot", "preserveNullAndEmptyArrays": True}},
            {"$group": {
                "_id": {"$ifNull": [{"$arrayElemAt": ["$snapshot.data.standardization_status", 0]}, "N/A"]},
                "count": {"$sum": 1}
            }}
        ]
        
        status_counts = {"PENDING": 0, "REJECTED": 0, "ACCEPTED": 0, "ON HOLD": 0, "N/A": 0}
        async for s_doc in db[EXECUTION_INFO_COL].aggregate(status_agg):
            status_key = str(s_doc.get("_id") or "N/A").upper()
            if status_key in status_counts:
                status_counts[status_key] = s_doc["count"]
            else:
                status_counts["N/A"] += s_doc["count"]

        return {
            "status": "success",
            "total_invalid_records": len(invalid_records),
            "page": 1,
            "size": len(execution_ids),
            "returned_records": len(invalid_records),
            "summary": {**summary_counts, **status_counts},
            "data": invalid_records
        }
    except Exception as e:
        print(f"DEBUG ERROR in get_invalid_summary_batch: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

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



@router.get("/metadata-values/{type_name}/{value}")
async def get_metadata_for_value(type_name: str, value: str):
    """
    Given a primary field type (e.g. 'CPUModel') and a selected value (e.g. '7543'),
    returns all metadata configurations associated with that value from the masterlist,
    along with their mapping paths.
    
    Use case: When user selects a value from the dropdown, this populates
    the dependent metadata fields (Family, coreCount, etc.) with valid options.
    """
    db = get_db()
    
    # Fetch all published masterlist records matching this type and value
    cursor = db[MASTERLIST_COL].find({
        "type": type_name,
        "data.value": value,
        "status": "Published"
    })
    
    records = await cursor.to_list(length=100)
    
    if not records:
        return {
            "status": "success",
            "type": type_name,
            "value": value,
            "metadata_records": [],
            "total_records": 0
        }
    
    metadata_records = []
    for record in records:
        record_id = record.get("`_id`") or record.get("id") or str(record.get("_id", ""))
        if isinstance(record_id, dict) and "$oid" in record_id:
            record_id = record_id["$oid"]
        
        data = record.get("data", {})
        meta = data.get("metadata", {})
        
        if not isinstance(meta, dict):
            continue
        
        meta_fields = {}
        meta_mappings = {}
        
        for mk, mv in meta.items():
            if mk.startswith("mapping_") or mk == "mapping":
                continue
            
            # Find the mapping for this metadata key
            lookup_key = f"mapping_{mk}".lower()
            mapping_path = None
            for k, v in meta.items():
                if k.lower() == lookup_key:
                    mapping_path = v
                    break
            if not mapping_path:
                mapping_path = meta.get("mapping", "")
            
            meta_fields[mk] = str(mv).strip()
            meta_mappings[mk] = mapping_path or ""
        
        if meta_fields:
            metadata_records.append({
                "_id": str(record_id),
                "metadata": meta_fields,
                "metadata_mappings": meta_mappings
            })
    
    return {
        "status": "success",
        "type": type_name,
        "value": value,
        "metadata_records": metadata_records,
        "total_records": len(metadata_records)
    }

@router.get("/validation-counts")
async def get_validation_counts():
    """
    Asynchronously returns the count of valid, invalid, and missing data for all mapped parameters.
    Dynamically discovers parameter types from the masterlist.
    Returns from cache instantly if within TTL.
    """
    global _report_cache
    if _report_cache["counts_metrics"]["value"] is not None and (time.time() - _report_cache["counts_metrics"]["updated_at"]) <= CACHE_TTL:
        return _report_cache["counts_metrics"]["value"]
        
    db = get_db()
    mappings = await build_mappings()
    
    facet_dict: Dict[str, Any] = {}
    for t in mappings.keys():
        facet_dict[t] = [
            {"$group": {
                "_id": None,
                "valid":   {"$sum": {"$cond": [{"$in": [t, {"$ifNull": ["$invalidFields", []]}]}, 0, 1]}},
                "invalid": {"$sum": {"$cond": [{"$in": [t, {"$ifNull": ["$invalidFields", []]}]}, 1, 0]}},
            }}
        ]
        
    facet_dict["total_docs"] = [{"$count": "total"}]
    
    pipeline = [
        {"$group": {
            "_id": "$benchmarkExecutionID",
            "invalidPayload": {"$first": "$invalidPayload"}
        }},
        {"$facet": facet_dict}
    ]
    
    cursor = db[EXECUTION_INFO_COL].aggregate(pipeline)
    result = await cursor.to_list(length=1)
    
    counts = {}
    total_docs = 0
    if result and len(result) > 0:
        res = result[0]
        total_docs = res.get("total_docs", [{"total": 0}])[0].get("total", 0) if res.get("total_docs") else 0
        
        for t in mappings.keys():
            t_data = res.get(t, [{"valid": 0, "invalid": 0}])[0]
            counts[t] = {
                "valid":   t_data.get("valid",   0),
                "invalid": t_data.get("invalid", 0),
            }
    
    response_payload = {
        "status": "success",
        "total_records_processed": total_docs,
        "counts_per_parameter": counts
    }
    
    _report_cache["counts_metrics"]["value"] = response_payload
    _report_cache["counts_metrics"]["updated_at"] = time.time()
    
    return response_payload


    
@router.get("/snapshot-records/{Execution_id}")
async def get_snapshot_records(Execution_id: str):
    """
    Fetches a specific record from the snapshot collection by Execution_id (Path Parameter).
    Flattens invalid metadata into a simple Data array with mappings.
    """
    db = get_db()
    Execution_id = Execution_id.strip()
    
    doc = await db[SNAPSHOT_COL].find_one({"execution_id": Execution_id})
    
    if not doc or not doc.get("data"):
        return {
            "status": "error",
            "message": f"No snapshot record found for Execution_id: {Execution_id}"
        }

    # Fetch metadata from ExecutionInfo
    exec_meta = await db[EXECUTION_INFO_COL].find_one({"benchmarkExecutionID": Execution_id})
    if not exec_meta:
        # Fallback to empty if not found, though it should exist
        exec_meta = {}

    item = doc["data"][0]
    validator = await get_validator()
    
    if exec_meta:
        # Live-evaluate the execution info against today's correct masterlist rules
        invalid_payload, field_status = await validator.validate_doc(db, exec_meta)
        if len(invalid_payload) == 0:
            # The record legally passes all current validation rules.
            # Flag it as valid natively!
            await db[EXECUTION_INFO_COL].update_one(
                {"benchmarkExecutionID": Execution_id},
                {
                    "$set": {"isValid": True},
                    "$unset": {
                        "fieldStatus": "", 
                        "invalidPayload": "",
                        "validated": "", 
                        "standardized": ""
                    }
                }
            )
            
            # Make sure we preserve the snapshot for the history/Accepted tab
            current_status = str(item.get("standardization_status", "")).upper()
            if current_status not in ["ACCEPTED", "REJECTED", "ON HOLD"]:
                await db[SNAPSHOT_COL].update_one(
                    {"execution_id": Execution_id},
                    {"$set": {"data.0.standardization_status": "ACCEPTED"}}
                )
                item["standardization_status"] = "ACCEPTED"
            
            # We no longer delete the snapshot nor return early. We let the function continue
            # so the UI can fetch and display the full history of this Accepted record!
            
    # Fetch any draft records for this execution to include in the response
    draft_cursor = db[MASTERLIST_COL].find({"execution_id": Execution_id, "status": "Draft"})
    draft_records = await draft_cursor.to_list(None)
    
    # Create a map for quick lookup: { (type.lower(), value): flattened_draft }
    draft_map = {}
    for dr in draft_records:
        # Construct the flattened structure as requested
        d_type = dr.get("type", "Unknown")
        d_data = dr.get("data", {})
        
        d_flat = {
            d_type: d_data.get("value")
        }
        
        # Capture all internal data and metadata into the flattened root
        for k, v in d_data.items():
            k_low = k.lower()
            if k not in ["metadata", "value"] and k_low != "mapping" and "suttype" not in k_low:
                d_flat[k_low] = v
        
        # Flatten metadata fields (e.g., family, corecount)
        for k, v in d_data.get("metadata", {}).items():
            if not k.startswith("mapping_"):
                d_flat[k.lower()] = v
        
        # Key by type for precise mapping to invalid fields within this execution
        d_type = dr.get("type", "").lower()
        draft_map[d_type] = d_flat

    # Fetch mapping and validation details dynamically for EACH individual field
    type_mappings = {}
    data_list = []
    
    # Process each invalid primary field from the snapshot record
    for meta in item.get("invalidValues", []):
        field_name = meta.get("field")
        if not field_name:
            continue
            
        if field_name not in type_mappings:
            type_mappings[field_name] = await get_masterlist_mappings(field_name)
            
        val = meta.get("value")
        
        # 1. Build existing_data for this field (primary field + metadata)
        field_existing_data = []
        field_existing_data.append({
            "field": field_name,
            "value": val,
            "datatype": meta.get("datatype", validator.field_types.get(field_name, "STRING").lower()),
            "validation_status": meta.get("validation_status")
        })
        
        for support in meta.get("metadata", []):
            field_existing_data.append({
                "field": support.get("name"),
                "value": support.get("value"),
                "datatype": support.get("datatype", validator.field_types.get(support.get("name"), "STRING").lower()),
                "validation_status": support.get("validation_status")
            })
            
        # 2. Build suggestions for this field directly from the snapshot
        saved_comparing = meta.get("comparingData", [])
        field_suggestions = []
        
        for saved_sug in saved_comparing:
            sug_key = next((k for k in saved_sug if k.startswith("suggestion")), None)
            score_key = next((k for k in saved_sug if k.startswith("score")), None)
            sug_val = saved_sug.get(sug_key) if sug_key else None
            score_val = saved_sug.get(score_key, 0) if score_key else 0
            
            sug_entry = {
                field_name.lower(): sug_val,
                "score": score_val,
                "status": saved_sug.get("status", "PENDING"),
                "_id": saved_sug.get("_id")
            }
            
            # Extract metadata for this specific suggestion
            for support in meta.get("metadata", []):
                m_name = support.get("name")
                if not m_name: continue
                
                m_comparing = support.get("comparingData", [])
                m_val = "None"
                # Find the matching suggestion for this metadata field by _id or suggestion key
                for m_sug in m_comparing:
                    if saved_sug.get("_id") and m_sug.get("_id") == saved_sug.get("_id"):
                        m_val_key = next((k for k in m_sug if k.startswith("suggestion")), None)
                        if m_val_key: m_val = m_sug.get(m_val_key)
                        break
                    elif sug_key and sug_key in m_sug:
                        m_val = m_sug.get(sug_key)
                        break
                
                sug_entry[m_name.lower()] = m_val
                
            field_suggestions.append(sug_entry)
            
        # 3. Add Draft Record if available for this specific field type
        field_draft = draft_map.get(field_name.lower())
            
        data_list.append({
            "invalid_field": field_name,
            "currentStatus": meta.get("currentStatus", "invalid"),
            "existing_data": field_existing_data,
            "suggestions": field_suggestions,
            "draft_records": field_draft
        })
    
    # Restructure history into changes array
    raw_history = item.get("history", {})
    hist_from = raw_history.get("from") or []
    hist_to = raw_history.get("to") or []
    hist_fields = raw_history.get("valueField") or []
    hist_source = raw_history.get("source") or []
    
    if not isinstance(hist_from, list): hist_from = [hist_from]
    if not isinstance(hist_to, list): hist_to = [hist_to]
    if not isinstance(hist_fields, list): hist_fields = [hist_fields]
    if not isinstance(hist_source, list): hist_source = [hist_source]
    
    individual_changes = []
    for idx in range(len(hist_fields)):
        f = hist_fields[idx] if idx < len(hist_fields) else ""
        frm = hist_from[idx] if idx < len(hist_from) else ""
        to = hist_to[idx] if idx < len(hist_to) else ""
        src = hist_source[idx] if idx < len(hist_source) else ""
        
        individual_changes.append({
            "field": f,
            "from": frm,
            "to": to,
            "source": src
        })
        
    # Build comprehensive dependency mapping for perfect grouping reconstruction
    field_to_primary_map = {}
    metadata_dependencies = {}
    
    # 1. First Pass: Register all primary fields
    for meta in item.get("invalidValues", []):
        p_field = meta.get("field")
        if p_field:
            p_lower = p_field.lower()
            field_to_primary_map[p_lower] = p_field
            metadata_dependencies[p_lower] = set()
            
    # 2. Second Pass: Register metadata fields (avoiding overwriting primary mappings)
    for meta in item.get("invalidValues", []):
        p_field = meta.get("field")
        if p_field:
            p_lower = p_field.lower()
            for supp in meta.get("metadata", []):
                m_name = supp.get("name")
                if m_name:
                    m_lower = m_name.lower()
                    metadata_dependencies[p_lower].add(m_lower)
                    # Protect primary field grouping: Only map to parent if not already a primary field
                    if m_lower not in field_to_primary_map:
                        field_to_primary_map[m_lower] = p_field
                    
    # Group changes sequentially, perfectly isolating overlapping names
    grouped_changes_list = []
    
    for change_obj in individual_changes:
        f_name = change_obj["field"]
        f_lower = f_name.lower()
        src = change_obj.get("source", "")
        
        is_cascaded = (src == "cascaded")
        
        # Robust heuristic fallback for existing snapshot records missing the "cascaded" tag
        if not is_cascaded and grouped_changes_list:
            current_primary_lower = grouped_changes_list[-1]["field"].lower()
            if f_lower in metadata_dependencies.get(current_primary_lower, set()):
                is_cascaded = True
                
        if not is_cascaded:
            mapped_primary = field_to_primary_map.get(f_lower, f_name)
            
            if not grouped_changes_list or grouped_changes_list[-1]["field"] != mapped_primary:
                grouped_changes_list.append({
                    "field": mapped_primary,
                    "changes": []
                })
                
        # Handle case where history explicitly starts with a cascaded tag (failsafe)
        if not grouped_changes_list:
            grouped_changes_list.append({
                "field": field_to_primary_map.get(f_lower, f_name),
                "changes": []
            })
            
        filtered_change = {"field": change_obj["field"], "from": change_obj["from"], "to": change_obj["to"]}
        grouped_changes_list[-1]["changes"].append(filtered_change)
        
    grouped_history_changes = grouped_changes_list
        
    # Get execution info for detailed response
    sut_type = exec_meta.get("sutInstanceMetadata.sutType") if "sutInstanceMetadata.sutType" in exec_meta else exec_meta.get("sutInstanceMetadata", {}).get("sutType")
    
    # Normalize createdOn: BSON Date / datetime → plain ISO string
    raw_created = exec_meta.get("createdOn")
    if isinstance(raw_created, datetime):
        created_on = raw_created.strftime("%Y-%m-%dT%H:%M:%S.%f")
    elif isinstance(raw_created, dict) and "$date" in raw_created:
        created_on = raw_created["$date"]
    else:
        created_on = raw_created
    
    return {
        "snapshot_id": doc.get("snapshot_id"),
        "execution_details": {
            "execution_id":      doc.get("execution_id"),
            "benchmarkType":     exec_meta.get("benchmarkType"),
            "benchmarkCategory": exec_meta.get("benchmarkCategory"),
            "sutType":           sut_type,
            "runCategory":       exec_meta.get("runCategory"),
            "createdOn":         created_on,
            "tester":            exec_meta.get("tester"),
            "resultType":        exec_meta.get("resultType"),
        },
        "data": data_list,
        "standardization_status": item.get("standardization_status", "PENDING"),
        "reason": item.get("reason"),
        "history": {
            "updatedOn": raw_history.get("updatedOn"),
            "updatedBy": raw_history.get("updatedBy"),
            "changes": grouped_history_changes
        }
    }

@router.get("/unique-values")
async def get_unique_values(parameterName: Optional[str] = Query(None)):
    """
    Fetches unique values for all validated parameters from the masterlist collection.
    Now fully dynamic: discovers all field paths from the masterlist structure.
    """
    db = get_db()
    field_map = await _get_dynamic_field_map(db)
    mappings = await build_mappings()
    
    # Discovery map for checking valid parameters
    all_params = list(mappings.keys())
    param_map = {p.lower(): p for p in all_params}
    
    # Get all top-level types to distinguish between primary values and metadata
    all_types = await db[MASTERLIST_COL].distinct("type", {"status": "Published"})
    type_set = set(all_types)

    if parameterName:
        param_norm = parameterName.lower()
        
        # Check if the parameter exists in our dynamic field map
        if param_norm in field_map:
            rule = field_map[param_norm]
            query = {"status": "Published", "type": rule["type"]}
            values = await db[MASTERLIST_COL].distinct(rule["path"], query)
            actual_param = parameterName # Keep user's casing for the response
        else:
            # Fallback for parameters not explicitly discovered (should be rare)
            if param_norm not in param_map:
                return {
                    "status": "error",
                    "message": f"Invalid parameterName. Supported values: {list(field_map.keys())}"
                }
            
            actual_param = param_map[param_norm]
            if actual_param in type_set:
                values = await db[MASTERLIST_COL].distinct("data.value", {"type": actual_param, "status": "Published"})
            else:
                values = await db[MASTERLIST_COL].distinct(f"data.metadata.{actual_param}", {"status": "Published"})
            
        return {
            "status": "success",
            "unique_values": {
                actual_param: sorted(list(set(str(v).strip() for v in values if v is not None and v != "")))
            }
        }

    # Default: Return all unique data lists dynamically
    unique_data = await _get_masterlist_all_unique_values(db)

    return {
        "status": "success",
        "unique_values": unique_data
    }

async def get_masterlist_values(field_type: str) -> List[str]:
    """Helper to fetch unique published values for a masterlist type."""
    db = get_db()
    values = await db[MASTERLIST_COL].distinct("data.value", {"type": field_type, "status": "Published"})
    return [str(v) for v in values if v]

@router.get("/search-snapshots")
async def search_snapshots(
    status: str = Query("PENDING", description="Filter by status: PENDING, REJECTED, ACCEPTED, 'On Hold'"),
    benchmarkType: Optional[str] = Query(None),
    benchmarkCategory: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500)
):
    db = get_db()
    
    # Fuzzy resolution
    resolved = await resolve_fuzzy_benchmarks(benchmarkType, benchmarkCategory)
    
    # 1. First, search ExecutionInfo to get the IDs of benchmarks that match
    exec_query = {}
    if "benchmarkType" in resolved:
        if resolved.get("benchmarkType_is_fuzzy"):
            exec_query["benchmarkType"] = resolved["benchmarkType"]
        else:
            exec_query["benchmarkType"] = {"$regex": resolved["benchmarkType"], "$options": "i"}
            
    if "benchmarkCategory" in resolved:
        if resolved.get("benchmarkCategory_is_fuzzy"):
            exec_query["benchmarkCategory"] = resolved["benchmarkCategory"]
        else:
            exec_query["benchmarkCategory"] = {"$regex": resolved["benchmarkCategory"], "$options": "i"}

    if search:
        search_regex = {"$regex": search, "$options": "i"}
        # Fuzzy resolution for both Type and Category
        resolved = await resolve_fuzzy_benchmarks(benchmarkType=search, benchmarkCategory=search)
        or_filters = [{"benchmarkExecutionID": search_regex}]
        
        if "benchmarkType" in resolved:
            if resolved.get("benchmarkType_is_fuzzy"):
                or_filters.append({"benchmarkType": resolved["benchmarkType"]})
            else:
                or_filters.append({"benchmarkType": search_regex})
        
        if "benchmarkCategory" in resolved:
            if resolved.get("benchmarkCategory_is_fuzzy"):
                or_filters.append({"benchmarkCategory": resolved["benchmarkCategory"]})
            else:
                or_filters.append({"benchmarkCategory": search_regex})
        
        # Always fallback to general regex on all three if no fuzzy matches found yet
        if len(or_filters) == 1:
            or_filters.extend([
                {"benchmarkType": search_regex},
                {"benchmarkCategory": search_regex}
            ])
            
        exec_query["$or"] = or_filters

    if not exec_query:
        return {"status": "success", "data": [], "message": "No search parameters provided."}

    # Get matching IDs (limited by a reasonable amount to prevent enormous $in clauses)
    # Actually, we can just use the query to find in ExecutionInfo and THEN snapshot
    matching_ids = await db[EXECUTION_INFO_COL].distinct("benchmarkExecutionID", exec_query)
    
    if not matching_ids:
        return {"status": "success", "data": [], "count": 0}

    skip_count = (page - 1) * size
    
    # 2. Query snapshots for these IDs
    cursor = db[SNAPSHOT_COL].find({"execution_id": {"$in": matching_ids}}).sort([("_id", -1)]).skip(skip_count).limit(size)
    
    results = []
    async for doc in cursor:
        exec_id = doc.get("execution_id")
        # Fetch metadata for this specific record (cached or fast lookup)
        exec_meta = await db[EXECUTION_INFO_COL].find_one({"benchmarkExecutionID": exec_id})
        
        item = doc["data"][0] if doc.get("data") else {}
        results.append({
            "snapshot_id": doc.get("snapshot_id"),
            "execution_id": exec_id,
            "benchmarkType": exec_meta.get("benchmarkType") if exec_meta else None,
            "benchmarkCategory": exec_meta.get("benchmarkCategory") if exec_meta else None,
            "runCategory": exec_meta.get("runCategory") if exec_meta else None,
            "createdOn": exec_meta.get("createdOn") if exec_meta else None,
            "tester": exec_meta.get("tester") if exec_meta else None,
            "standardization_status": item.get("standardization_status"),
            "history": item.get("history", {})
        })

    return {
        "status": "success",
        "count": len(results),
        "page": page,
        "size": size,
        "data": results
    }

async def resolve_fuzzy_benchmarks(benchmarkType: Optional[str] = None, benchmarkCategory: Optional[str] = None) -> Dict[str, Any]:
    """Helper to resolve fuzzy benchmark terms into exact masterlist values."""
    resolved = {}
    if benchmarkType:
        valid_types = await get_masterlist_values("BenchmarkType")
        valid_map = {v.lower(): v for v in valid_types}
        match_res = process.extractOne(benchmarkType.lower(), valid_map.keys(), score_cutoff=60)
        if match_res:
             match_str = match_res[0]
             resolved["benchmarkType"] = valid_map[match_str]
             resolved["benchmarkType_is_fuzzy"] = True
        else:
             resolved["benchmarkType"] = benchmarkType
             resolved["benchmarkType_is_fuzzy"] = False

    if benchmarkCategory:
        valid_cats = await get_masterlist_values("BenchmarkCategory")
        valid_map = {v.lower(): v for v in valid_cats}
        match_res = process.extractOne(benchmarkCategory.lower(), valid_map.keys(), score_cutoff=60)
        if match_res:
             match_str = match_res[0]
             resolved["benchmarkCategory"] = valid_map[match_str]
             resolved["benchmarkCategory_is_fuzzy"] = True
        else:
             resolved["benchmarkCategory"] = benchmarkCategory
             resolved["benchmarkCategory_is_fuzzy"] = False
    
    return resolved


# @router.put("/approve-suggestion")
# async def approve_suggestion(req: ApproveSuggestionRequest):
#     try:
#         db = get_db()
   
#         # 1. Fetch Snapshot
#         snap = await db[SNAPSHOT_COL].find_one({"execution_id": req.execution_id})
#         if not snap or not snap.get("data"):
#             return {"status": "error", "message": f"Snapshot not found for Execution ID: {req.execution_id}"}
       
#         snap_data = snap["data"][0]
#         invalid_values = snap_data.get("invalidValues", [])
       
#         # 2. Identify the selected field and suggestion (supporting nested metadata)
#         target_item = None
#         target_mapping = None
#         original_value = None
#         suggestion_found = False
       
#         # Check top-level invalid fields first
#         for item in invalid_values:
#             if item.get("field") == req.field_name:
#                 target_item = item
#                 original_value = item.get("value")
#                 # Fetch primary mapping
#                 m_info = await get_masterlist_mappings(req.field_name)
#                 target_mapping = m_info.get("mapping")
#                 break
           
#             # Check nested metadata fields
#             for meta_item in item.get("metadata", []):
#                 if meta_item.get("name") == req.field_name:
#                     target_item = meta_item
#                     original_value = meta_item.get("value")
#                     # Fetch metadata-specific mapping
#                     m_info = await get_masterlist_mappings(item.get("field"))
#                     target_mapping = m_info.get("metadata_mappings", {}).get(req.field_name)
#                     break
#             if target_item: break
   
#         if not target_item:
#             return {"status": "error", "message": f"Field '{req.field_name}' not found in snapshot."}
           
#         # 3. Update suggestion statuses
#         comparing_data = target_item.get("comparingData", [])
#         accepted_sug_num = None
       
#         # First pass: determine which suggestion is accepted
#         # Priority: explicit masterlist_id > _id in extra > metadata matching > first value match
#         accepted_key = None
#         req_id = req.masterlist_id or (req.model_extra.get("_id") if req.model_extra else None)
       
#         if req_id:
#             for sug in comparing_data:
#                 if sug.get("_id") == req_id:
#                     accepted_key = next((k for k in sug.keys() if k.startswith("suggestion")), None)
#                     break
       
#         if not accepted_key:
#             # Find all candidates whose primary value matches
#             candidates = []
#             for sug in comparing_data:
#                 match_key = next((k for k in sug.keys() if k.startswith("suggestion")), None)
#                 if match_key and str(sug[match_key]) == str(req.accepted_value):
#                     candidates.append(match_key)
                   
#             if len(candidates) == 1:
#                 accepted_key = candidates[0]
#             elif len(candidates) > 1:
#                 # Disambiguate using metadata provided in the request
#                 best_match_key = candidates[0]
#                 best_match_score = -1
               
#                 for cand_key in candidates:
#                     score = 0
#                     for m_item in target_item.get("metadata", []):
#                         m_name = m_item.get("name", "")
                       
#                         cand_m_val = None
#                         for m_sug in m_item.get("comparingData", []):
#                             if cand_key in m_sug:
#                                 cand_m_val = m_sug[cand_key]
#                                 break
                               
#                         if cand_m_val is None:
#                             continue
                           
#                         # Extract the UI-provided value for this metadata field
#                         ui_val = None
#                         if hasattr(req, m_name):
#                             ui_val = getattr(req, m_name, None)
                       
#                         # 2. Check the new metadata object (Priority)
#                         if ui_val is None and req.metadata:
#                             if m_name in req.metadata:
#                                 ui_val = req.metadata[m_name]
#                             elif m_name.lower() in req.metadata:
#                                 ui_val = req.metadata[m_name.lower()]
                       
#                         # 3. Fallback to top-level extra properties
#                         if ui_val is None and req.model_extra:
#                             if m_name in req.model_extra:
#                                 ui_val = req.model_extra[m_name]
#                             elif m_name.lower() in req.model_extra:
#                                 ui_val = req.model_extra[m_name.lower()]
                       
#                         # Special handling for coreCount aliases
#                         if ui_val is None and m_name.lower() in ["corecount", "cpu(s)"]:
#                             ui_val = req.coreCount
#                             if ui_val is None:
#                                 # Check metadata and model_extra for common aliases
#                                 sources = [req.metadata, req.model_extra]
#                                 for src in sources:
#                                     if src:
#                                         ui_val = src.get("CPU(s)") or src.get("cpu(s)")
#                                         if ui_val is not None: break
                       
#                         if ui_val is not None and str(cand_m_val).lower() == str(ui_val).lower():
#                             score += 1
                           
#                     if score > best_match_score:
#                         best_match_score = score
#                         best_match_key = cand_key
                       
#                 accepted_key = best_match_key
 
#         # Second pass: apply the selected accepted_key
#         for sug in comparing_data:
#             match_key = next((k for k in sug.keys() if k.startswith("suggestion")), None)
#             if not match_key: continue
           
#             if match_key == accepted_key:
#                 sug["status"] = "Accepted"
#                 suggestion_found = True
#                 accepted_sug_num = match_key.replace("suggestion", "")
#             else:
#                 sug["status"] = "Rejected"
       
#         # Determine the source of the accepted value
#         value_source = "suggestion" if suggestion_found else "dropdown"
               
#         # Always set to valid since we are finalizing a correction
#         target_item["validation_status"] = "valid"
#         target_item["currentStatus"] = req.currentStatus
           
#         # 4. Propagate the change to Executioninfo if a mapping exists
#         if target_mapping:
#             safe_mapping = target_mapping.replace(".sut.", ".sut.0.")
#             await db[EXECUTION_INFO_COL].update_one(
#                 {"benchmarkExecutionID": req.execution_id},
#                 {"$set": {safe_mapping: req.accepted_value}}
#             )
       
#         # 4.1 Collect potential manual overrides from the request (Priority: explicit fields > metadata > model_extra)
#         manual_overrides = {}
       
#         # Helper to safely add values to overrides
#         def add_override(k, v):
#             if v is not None and str(v).strip() not in ["", "string", "None", "null"]:
#                 if k not in manual_overrides: manual_overrides[k] = v
#                 kl = k.lower()
#                 if kl not in manual_overrides: manual_overrides[kl] = v
 
#         if req.metadata:
#             for k, v in req.metadata.items(): add_override(k, v)
#         if req.model_extra:
#             for k, v in req.model_extra.items(): add_override(k, v)
#         if req.coreCount:
#             add_override("coreCount", req.coreCount)
#             add_override("corecount", req.coreCount)
#             add_override("CPU(s)", req.coreCount)
#             add_override("cpu(s)", req.coreCount)
       
#         # 4b. CASCADE: If this is a primary field, apply the same suggestion status to ALL metadata
#         is_primary_field = False
#         parent_item = None
#         cascaded_changes = []  # Track (field_name, from_value, to_value) for history
       
#         for item in invalid_values:
#             if item.get("field") == req.field_name:
#                 is_primary_field = True
#                 parent_item = item
#                 break
       
#         if is_primary_field and parent_item:
#             # Fetch metadata mappings for this primary field type
#             m_info = await get_masterlist_mappings(req.field_name)
#             meta_mappings = m_info.get("metadata_mappings", {})
           
#             # If Dropdown, dynamically fetch the Masterlist Record for the exact value they chose!
#             dropdown_metadata = {}
#             if value_source == "dropdown":
#                 # Find the exact record using _id or metadata matching
#                 dropdown_query = {
#                     "type": {"$regex": f"^{req.field_name}$", "$options": "i"},
#                     "data.value": req.accepted_value,
#                     "status": "Published"
#                 }
               
#                 req_id = req.masterlist_id or (req.model_extra.get("_id") if req.model_extra else None)
#                 dropdown_ml_record = None
               
#                 if req_id:
#                     dropdown_ml_record = await db[MASTERLIST_COL].find_one({"_id": req_id})
               
#                 if not dropdown_ml_record:
#                     # Find all records with this value and pick the best metadata match
#                     ml_candidates = await db[MASTERLIST_COL].find(dropdown_query).to_list(None)
#                     if len(ml_candidates) == 1:
#                         dropdown_ml_record = ml_candidates[0]
#                     elif len(ml_candidates) > 1:
#                         # Match against req.model_extra
#                         best_ml = ml_candidates[0]
#                         best_score = -1
#                         for cand in ml_candidates:
#                             score = 0
#                             cand_meta = cand.get("data", {}).get("metadata", {})
#                             for mk, mv in cand_meta.items():
#                                 if mk.startswith("mapping_"): continue
#                                 ui_val = req.model_extra.get(mk) or req.model_extra.get(mk.lower())
#                                 if ui_val is None and mk.lower() == "corecount":
#                                     ui_val = req.coreCount or req.model_extra.get("CPU(s)") or req.model_extra.get("cpu(s)")
#                                 if ui_val is not None and str(mv).lower() == str(ui_val).lower():
#                                     score += 1
#                             if score > best_score:
#                                 best_score = score
#                                 best_ml = cand
#                         dropdown_ml_record = best_ml
               
#                 if dropdown_ml_record:
#                     dropdown_metadata = dropdown_ml_record.get("data", {}).get("metadata", {})
           
#             # Iterate over ALL mapped metadata fields for this primary field type
#             for meta_name, meta_mapping in meta_mappings.items():
#                 # 0. Identify the corresponding item in the snapshot metadata (if any)
#                 meta_item = next((m for m in parent_item.get("metadata", []) if m.get("name") == meta_name), None)
               
#                 meta_original_value = meta_item.get("value") if meta_item else "Unknown"
#                 meta_accepted_value = None
#                 meta_comparing = meta_item.get("comparingData", []) if meta_item else []
               
#                 # 1. PRIORITY: Manual Override (Deliberate user edit from the request)
#                 meta_source = "manual_edit"
#                 # Look for exact or case-insensitive match in overrides
#                 manual_val = manual_overrides.get(meta_name) or manual_overrides.get(str(meta_name).lower())
               
#                 if manual_val is not None:
#                     # If the user edited it, we use their value!
#                     meta_accepted_value = manual_val
                    
#                     # We must still update the statuses of the comparing data to Rejected
#                     for sug in meta_comparing:
#                         sug["status"] = "Rejected"
#                 else:
#                     # 2. PRIORITY: Suggestion (Matches the accepted primary suggestion)
#                     meta_source = "cascaded"
#                     if accepted_sug_num and meta_comparing:
#                         for sug in meta_comparing:
#                             sug_key = next((k for k in sug if k.startswith("suggestion")), None)
#                             if sug_key and sug_key == f"suggestion{accepted_sug_num}":
#                                 sug["status"] = "Accepted"
#                                 meta_accepted_value = sug[sug_key]
#                                 meta_source = "suggestion"
#                             else:
#                                 sug["status"] = "Rejected"
#                     else:
#                         # Not a suggestion approval or no suggestions for this meta field, reject all if they exist
#                         for sug in meta_comparing:
#                             sug["status"] = "Rejected"
               
#                 # 3. PRIORITY: Masterlist Record (Dropdown source only)
#                 if meta_accepted_value is None and value_source == "dropdown":
#                     # Default to "None" if missing in masterlist record
#                     meta_accepted_value = "None"
#                     meta_source = "masterlist"
#                     for k, v in dropdown_metadata.items():
#                         if k.lower() == str(meta_name).lower():
#                             if v is not None and str(v).strip() != "":
#                                 meta_accepted_value = v
#                             break
               
#                 # 4. Final Fallback: If we have NO new value, skip this field (don't overwrite with None)
#                 if meta_accepted_value is None:
#                     continue
 
#                 # Mark metadata as valid in the snapshot if it exists
#                 if meta_item:
#                     meta_item["validation_status"] = "valid"
               
#                 # Propagate metadata value to ExecutionInfo
#                 if meta_mapping:
#                     safe_meta_mapping = meta_mapping.replace(".sut.", ".sut.0.")
#                     await db[EXECUTION_INFO_COL].update_one(
#                         {"benchmarkExecutionID": req.execution_id},
#                         {"$set": {safe_meta_mapping: meta_accepted_value}}
#                     )
               
#                 # Track for history
#                 cascaded_changes.append({
#                     "field": meta_name,
#                     "from": meta_original_value,
#                     "to": meta_accepted_value,
#                     "source": meta_source
#                 })
       
#         # 5. Check for Overall Validity (Standardization Status)
#         is_fully_resolved = True
#         for item in invalid_values:
#             if item.get("validation_status") != "valid":
#                 is_fully_resolved = False
#                 break
#             for meta in item.get("metadata", []):
#                 if meta.get("validation_status") != "valid":
#                     is_fully_resolved = False
#                     break
#             if not is_fully_resolved: break
   
#         # 6. Update History (BUILD THIS BEFORE FINAL SYNC)
#         history = snap_data.get("history", {})
#         orig_from = history.get("from")
#         orig_to = history.get("to")
#         orig_field = history.get("valueField")
#         orig_source = history.get("source")
       
#         new_from = orig_from if isinstance(orig_from, list) else ([orig_from] if orig_from else [])
#         new_to = orig_to if isinstance(orig_to, list) else ([orig_to] if orig_to else [])
#         new_field = orig_field if isinstance(orig_field, list) else ([orig_field] if orig_field else [])
#         new_source = orig_source if isinstance(orig_source, list) else ([orig_source] if orig_source else [])
       
#         # Add primary field history
#         new_from.append(original_value)
#         new_to.append(req.accepted_value)
#         new_field.append(req.field_name)
#         new_source.append(value_source)
       
#         # Add cascaded metadata history
#         for change in cascaded_changes:
#             new_from.append(change["from"])
#             new_to.append(change["to"])
#             new_field.append(change["field"])
#             new_source.append(change.get("source", "cascaded"))
   
#         snap_data["history"] = {
#             "updatedOn": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
#             "updatedBy": "xxx@amd.com",
#             "from": new_from,
#             "to": new_to,
#             "valueField": new_field,
#             "source": new_source
#         }
   
#         # 7. Final Acceptance Transition & Consistency Sync
#         if is_fully_resolved:
#             snap_data["standardization_status"] = "ACCEPTED"
           
#             # --- FINAL CONSISTENCY SYNC (Double-Sync driven by History) ---
#             ei_doc = await db[EXECUTION_INFO_COL].find_one({"benchmarkExecutionID": req.execution_id})
           
#             if ei_doc:
#                 # Build a lookup for mappings from the current snapshot structure
#                 mapping_lookup = {}
#                 for item in invalid_values:
#                     field_name = item.get("field")
#                     if field_name:
#                         mapping_lookup[field_name] = item.get("mapping")
#                     for meta in item.get("metadata", []):
#                         meta_name = meta.get("name")
#                         if meta_name:
#                             mapping_lookup[meta_name] = meta.get("mapping")
               
#                 # Sync ALL fields currently present in the final history to Executioninfo
#                 final_updates_applied = False
#                 for i, field_name in enumerate(new_field):
#                     m_path = mapping_lookup.get(field_name)
#                     m_val = new_to[i] if i < len(new_to) else None
                   
#                     if m_path and m_val is not None:
#                         final_updates_applied = True
#                         # A. Update Flattened literal key
#                         if m_path in ei_doc:
#                             ei_doc[m_path] = m_val
#                         # B. Update Nested Path
#                         _set_nested_key(ei_doc, m_path, m_val)
               
#                 if final_updates_applied:
#                     print(f"Applying Final History-Driven Double-Sync for {req.execution_id}")
#                     await db[EXECUTION_INFO_COL].replace_one(
#                         {"_id": ei_doc["_id"]},
#                         ei_doc
#                     )
#         else:
#             # Keep as PENDING if not all fields are resolved
#             snap_data["standardization_status"] = "PENDING"
   
#         # 7. Update Executioninfo with latest results
#         # Recalculate remaining invalid fields for the summary
#         current_invalid_fields = sorted(list(set(
#             [p.get("field") for p in invalid_values if p.get("validation_status") != "valid"] +
#             [m.get("name") for p in invalid_values for m in p.get("metadata", []) if m.get("validation_status") != "valid"]
#         )))
       
#         update_fields = {
#             "isValid": is_fully_resolved,
#             "invalidFields": current_invalid_fields,
#             "lastModifiedOn": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
#         }
       
#         # If fully resolved, ensure we clean up legacy fields
#         unset_fields = {}
#         if is_fully_resolved:
#             unset_fields = {
#                 "validated": "",
#                 "standardized": "",
#                 "fieldStatus": "",
#                 "invalidPayload": ""
#             }
           
#         await db[EXECUTION_INFO_COL].update_one(
#             {"benchmarkExecutionID": req.execution_id},
#             {"$set": update_fields, "$unset": unset_fields}
#         )
       
#         # 8. Save entire Snapshot back
#         await db[SNAPSHOT_COL].replace_one({"execution_id": req.execution_id}, snap)
       
#         # Broadcast update
#         await manager.broadcast({
#             "type": "PIPELINE_UPDATE",
#             "execution_id": req.execution_id,
#             "stage": "standardization completed",
#             "status": snap_data["standardization_status"],
#             "invalidFields": current_invalid_fields,
#             "benchmarkType": snap.get("benchmark_type"),
#             "benchmarkCategory": snap.get("benchmark_category"),
#             "updatedOn": snap_data["history"].get("updatedOn"),
#             "suggestionsCount": len(current_invalid_fields) > 0
#         })
#         await broadcast_summary(db)

#         return {
#             "status": "success",
#             "message": f"Successfully {'accepted suggestion' if value_source == 'suggestion' else 'applied custom value'} for '{req.field_name}' and updated Executioninfo.",
#             "execution_id": req.execution_id,
#             "updated_field": req.field_name,
#             "accepted_value": req.accepted_value,
#             "mapping_path": target_mapping,
#             "value_source": value_source
#         }
#     except Exception as e:
#         import traceback
#         error_details = traceback.format_exc()
#         print(f"CRITICAL ERROR in approve_suggestion: {str(e)}\n{error_details}")
#         raise HTTPException(
#             status_code=500,
#             detail={
#                 "error": str(e),
#                 "type": type(e).__name__,
#                 "stacktrace": error_details
#             }
#         )



@router.put("/approve-suggestion")
async def approve_suggestion(req: ApproveSuggestionRequest):
    try:
        db = get_db()
   
        # 1. Fetch Snapshot
        snap = await db[SNAPSHOT_COL].find_one({"execution_id": req.execution_id})
        if not snap or not snap.get("data"):
            return {"status": "error", "message": f"Snapshot not found for Execution ID: {req.execution_id}"}
       
        snap_data = snap["data"][0]
        invalid_values = snap_data.get("invalidValues", [])
       
        # 2. Identify the selected field and suggestion (supporting nested metadata)
        target_item = None
        target_mapping = None
        original_value = None
        suggestion_found = False
       
        # Check top-level invalid fields first
        for item in invalid_values:
            if item.get("field") == req.field_name:
                target_item = item
                original_value = item.get("value")
                # Fetch primary mapping
                m_info = await get_masterlist_mappings(req.field_name)
                target_mapping = m_info.get("mapping")
                break
           
            # Check nested metadata fields
            for meta_item in item.get("metadata", []):
                if meta_item.get("name") == req.field_name:
                    target_item = meta_item
                    original_value = meta_item.get("value")
                    # Fetch metadata-specific mapping
                    m_info = await get_masterlist_mappings(item.get("field"))
                    target_mapping = m_info.get("metadata_mappings", {}).get(req.field_name)
                    break
            if target_item: break
   
        if not target_item:
            return {"status": "error", "message": f"Field '{req.field_name}' not found in snapshot."}
           
        # 3. Update suggestion statuses
        comparing_data = target_item.get("comparingData", [])
        accepted_sug_num = None
       
        # First pass: determine which suggestion is accepted
        # Priority: masterlist_id > _id > metadata matching > first value match
        accepted_key = None
        req_id = req.model_extra.get("masterlist_id") or req.model_extra.get("_id") if req.model_extra else None
       
        if req_id:
            for sug in comparing_data:
                if sug.get("_id") == req_id:
                    accepted_key = next((k for k in sug.keys() if k.startswith("suggestion")), None)
                    break
       
        if not accepted_key:
            # Find all candidates whose primary value matches
            candidates = []
            for sug in comparing_data:
                match_key = next((k for k in sug.keys() if k.startswith("suggestion")), None)
                if match_key and str(sug[match_key]) == str(req.accepted_value):
                    candidates.append(match_key)
                   
            if len(candidates) == 1:
                accepted_key = candidates[0]
            elif len(candidates) > 1:
                # Disambiguate using metadata provided in the request
                best_match_key = candidates[0]
                best_match_score = -1
               
                for cand_key in candidates:
                    score = 0
                    for m_item in target_item.get("metadata", []):
                        m_name = m_item.get("name", "")
                       
                        cand_m_val = None
                        for m_sug in m_item.get("comparingData", []):
                            if cand_key in m_sug:
                                cand_m_val = m_sug[cand_key]
                                break
                               
                        if cand_m_val is None:
                            continue
                           
                        # Extract the UI-provided value for this metadata field
                        ui_val = None
                        if hasattr(req, m_name):
                            ui_val = getattr(req, m_name, None)
                       
                        # 2. Check the new metadata object (Priority)
                        if ui_val is None and req.metadata:
                            if m_name in req.metadata:
                                ui_val = req.metadata[m_name]
                            elif m_name.lower() in req.metadata:
                                ui_val = req.metadata[m_name.lower()]
                       
                        # 3. Fallback to top-level extra properties
                        if ui_val is None and req.model_extra:
                            if m_name in req.model_extra:
                                ui_val = req.model_extra[m_name]
                            elif m_name.lower() in req.model_extra:
                                ui_val = req.model_extra[m_name.lower()]
                       
                        # Special handling for coreCount aliases
                        if ui_val is None and m_name.lower() in ["corecount", "cpu(s)"]:
                            ui_val = req.coreCount
                            if ui_val is None:
                                # Check metadata and model_extra for common aliases
                                sources = [req.metadata, req.model_extra]
                                for src in sources:
                                    if src:
                                        ui_val = src.get("CPU(s)") or src.get("cpu(s)")
                                        if ui_val is not None: break
                       
                        if ui_val is not None and str(cand_m_val).lower() == str(ui_val).lower():
                            score += 1
                           
                    if score > best_match_score:
                        best_match_score = score
                        best_match_key = cand_key
                       
                accepted_key = best_match_key
 
        # Second pass: apply the selected accepted_key
        for sug in comparing_data:
            match_key = next((k for k in sug.keys() if k.startswith("suggestion")), None)
            if not match_key: continue
           
            if match_key == accepted_key:
                sug["status"] = "Accepted"
                suggestion_found = True
                accepted_sug_num = match_key.replace("suggestion", "")
            else:
                sug["status"] = "Rejected"
       
        # Determine the source of the accepted value
        value_source = "suggestion" if suggestion_found else "dropdown"
               
        # Always set to valid since we are finalizing a correction
        target_item["validation_status"] = "valid"
        target_item["currentStatus"] = req.currentStatus
           
        # 4. Propagate the change to Executioninfo if a mapping exists
        if target_mapping:
            safe_mapping = target_mapping.replace(".sut.", ".sut.0.")
            await db[EXECUTION_INFO_COL].update_one(
                {"benchmarkExecutionID": req.execution_id},
                {"$set": {safe_mapping: req.accepted_value}}
            )
       
        # 4.1 Collect potential manual overrides from the request (Priority: explicit fields > metadata > model_extra)
        manual_overrides = {}
       
        # Helper to safely add values to overrides
        def add_override(k, v):
            if v is not None and str(v).strip() not in ["", "string", "None", "null"]:
                if k not in manual_overrides: manual_overrides[k] = v
                kl = k.lower()
                if kl not in manual_overrides: manual_overrides[kl] = v
 
        if req.metadata:
            for k, v in req.metadata.items(): add_override(k, v)
        if req.model_extra:
            for k, v in req.model_extra.items(): add_override(k, v)
        if req.coreCount:
            add_override("coreCount", req.coreCount)
            add_override("corecount", req.coreCount)
            add_override("CPU(s)", req.coreCount)
            add_override("cpu(s)", req.coreCount)
       
        # 4b. CASCADE: If this is a primary field, apply the same suggestion status to ALL metadata
        is_primary_field = False
        parent_item = None
        cascaded_changes = []  # Track (field_name, from_value, to_value) for history
       
        for item in invalid_values:
            if item.get("field") == req.field_name:
                is_primary_field = True
                parent_item = item
                break
       
        if is_primary_field and parent_item:
            # Fetch metadata mappings for this primary field type
            m_info = await get_masterlist_mappings(req.field_name)
            meta_mappings = m_info.get("metadata_mappings", {})
           
            # If Dropdown, dynamically fetch the Masterlist Record for the exact value they chose!
            dropdown_metadata = {}
            if value_source == "dropdown":
                # Find the exact record using _id or metadata matching
                dropdown_query = {
                    "type": {"$regex": f"^{req.field_name}$", "$options": "i"},
                    "data.value": req.accepted_value,
                    "status": "Published"
                }
               
                req_id = req.model_extra.get("masterlist_id") or req.model_extra.get("_id") if req.model_extra else None
                dropdown_ml_record = None
               
                if req_id:
                    dropdown_ml_record = await db[MASTERLIST_COL].find_one({"_id": req_id})
               
                if not dropdown_ml_record:
                    # Find all records with this value and pick the best metadata match
                    ml_candidates = await db[MASTERLIST_COL].find(dropdown_query).to_list(None)
                    if len(ml_candidates) == 1:
                        dropdown_ml_record = ml_candidates[0]
                    elif len(ml_candidates) > 1:
                        # Match against req.model_extra
                        best_ml = ml_candidates[0]
                        best_score = -1
                        for cand in ml_candidates:
                            score = 0
                            cand_meta = cand.get("data", {}).get("metadata", {})
                            for mk, mv in cand_meta.items():
                                if mk.startswith("mapping_"): continue
                                ui_val = req.model_extra.get(mk) or req.model_extra.get(mk.lower())
                                if ui_val is None and mk.lower() == "corecount":
                                    ui_val = req.coreCount or req.model_extra.get("CPU(s)") or req.model_extra.get("cpu(s)")
                                if ui_val is not None and str(mv).lower() == str(ui_val).lower():
                                    score += 1
                            if score > best_score:
                                best_score = score
                                best_ml = cand
                        dropdown_ml_record = best_ml
               
                if dropdown_ml_record:
                    dropdown_metadata = dropdown_ml_record.get("data", {}).get("metadata", {})
           
            # Iterate over ALL mapped metadata fields for this primary field type
            for meta_name, meta_mapping in meta_mappings.items():
                # 0. Identify the corresponding item in the snapshot metadata (if any)
                meta_item = next((m for m in parent_item.get("metadata", []) if m.get("name") == meta_name), None)
               
                meta_original_value = meta_item.get("value") if meta_item else "Unknown"
                meta_accepted_value = None
                meta_comparing = meta_item.get("comparingData", []) if meta_item else []
               
                # 1. PRIORITY: Manual Override (Deliberate user edit from the request)
                meta_source = "manual_edit"
                # Look for exact or case-insensitive match in overrides
                manual_val = manual_overrides.get(meta_name) or manual_overrides.get(str(meta_name).lower())
               
                is_explicit_manual_override = False
                if manual_val is not None:
                    is_explicit_manual_override = True
                    if accepted_sug_num and meta_comparing:
                        for sug in meta_comparing:
                            sug_key = next((k for k in sug if k.startswith("suggestion")), None)
                            if sug_key == f"suggestion{accepted_sug_num}":
                                sug_val = str(sug.get(sug_key, "")).strip().lower()
                                man_val = str(manual_val).strip().lower()
                                if sug_val == man_val:
                                    is_explicit_manual_override = False
                                else:
                                    try:
                                        if float(sug.get(sug_key, 0)) == float(manual_val):
                                            is_explicit_manual_override = False
                                    except:
                                        if sug_val in ["none", "null", ""] and man_val in ["none", "null", ""]:
                                            is_explicit_manual_override = False
                                break

                if is_explicit_manual_override:
                    meta_accepted_value = manual_val
                    # Ensure all suggestions are rejected since we are overriding manually
                    for sug in meta_comparing:
                        sug["status"] = "Rejected"
                else:
                    # 2. PRIORITY: Suggestion (Matches the accepted primary suggestion)
                    if accepted_sug_num and meta_comparing:
                        meta_source = "suggestion"
                        for sug in meta_comparing:
                            sug_key = next((k for k in sug if k.startswith("suggestion")), None)
                            if sug_key and sug_key == f"suggestion{accepted_sug_num}":
                                sug["status"] = "Accepted"
                                meta_accepted_value = sug[sug_key]
                            else:
                                sug["status"] = "Rejected"
                    else:
                        # Not a suggestion approval or no suggestions for this meta field, reject all if they exist
                        meta_source = "cascaded"
                        for sug in meta_comparing:
                            sug["status"] = "Rejected"
               
                # 3. PRIORITY: Masterlist Record (Dropdown source only)
                if meta_accepted_value is None and value_source == "dropdown":
                    # Default to "None" if missing in masterlist record
                    meta_accepted_value = "None"
                    meta_source = "masterlist"
                    for k, v in dropdown_metadata.items():
                        if k.lower() == str(meta_name).lower():
                            if v is not None and str(v).strip() != "":
                                meta_accepted_value = v
                            break
               
                # 4. Final Fallback: If we have NO new value, skip this field (don't overwrite with None)
                if meta_accepted_value is None:
                    continue
 
                # Mark metadata as valid in the snapshot if it exists
                if meta_item:
                    meta_item["validation_status"] = "valid"
               
                # Propagate metadata value to ExecutionInfo
                if meta_mapping:
                    safe_meta_mapping = meta_mapping.replace(".sut.", ".sut.0.")
                    await db[EXECUTION_INFO_COL].update_one(
                        {"benchmarkExecutionID": req.execution_id},
                        {"$set": {safe_meta_mapping: meta_accepted_value}}
                    )
               
                # Track for history
                cascaded_changes.append({
                    "field": meta_name,
                    "from": meta_original_value,
                    "to": meta_accepted_value,
                    "source": meta_source
                })

        # 4.1a Apply standalone Manual CPU(s) / coreCount update if provided and missed by cascade
        manual_cpu_val = manual_overrides.get("cpu(s)") or manual_overrides.get("corecount")
       
        if manual_cpu_val is not None:
            # Enforce it in Executioninfo
            await db[EXECUTION_INFO_COL].update_one(
                {"benchmarkExecutionID": req.execution_id},
                {"$set": {"platformProfile.sut.0.Summary.CPU.CPU(s)": manual_cpu_val}}
            )
            # Find it in snapshot invalid_values to mark it valid if missed by the cascade
            for item in invalid_values:
                if item.get("field") in ["coreCount", "CPU(s)"] and item.get("validation_status") != "valid":
                    cascaded_changes.append({
                        "field": item.get("field"),
                        "from": item.get("value"),
                        "to": manual_cpu_val,
                        "source": "manual_edit"
                    })
                    item["validation_status"] = "valid"
                    item["currentStatus"] = req.currentStatus
                    for sug in item.get("comparingData", []):
                        sug["status"] = "Rejected"
                   
                for meta in item.get("metadata", []):
                    if meta.get("name") in ["coreCount", "CPU(s)"] and meta.get("validation_status") != "valid":
                        cascaded_changes.append({
                            "field": meta.get("name"),
                            "from": meta.get("value"),
                            "to": manual_cpu_val,
                            "source": "manual_edit"
                        })
                        meta["validation_status"] = "valid"
                        meta["currentStatus"] = req.currentStatus
                        for sug in meta.get("comparingData", []):
                            sug["status"] = "Rejected"

        # 5. Check for Overall Validity (Standardization Status)
        is_fully_resolved = True
        for item in invalid_values:
            if item.get("validation_status") != "valid":
                is_fully_resolved = False
                break
            for meta in item.get("metadata", []):
                if meta.get("validation_status") != "valid":
                    is_fully_resolved = False
                    break
            if not is_fully_resolved: break
   
        # 6. Update History (BUILD THIS BEFORE FINAL SYNC)
        history = snap_data.get("history", {})
        orig_from = history.get("from")
        orig_to = history.get("to")
        orig_field = history.get("valueField")
        orig_source = history.get("source")
       
        new_from = orig_from if isinstance(orig_from, list) else ([orig_from] if orig_from else [])
        new_to = orig_to if isinstance(orig_to, list) else ([orig_to] if orig_to else [])
        new_field = orig_field if isinstance(orig_field, list) else ([orig_field] if orig_field else [])
        new_source = orig_source if isinstance(orig_source, list) else ([orig_source] if orig_source else [])
       
        # Add primary field history
        new_from.append(original_value)
        new_to.append(req.accepted_value)
        new_field.append(req.field_name)
        new_source.append(value_source)
       
        # Add cascaded metadata history
        for change in cascaded_changes:
            new_from.append(change["from"])
            new_to.append(change["to"])
            new_field.append(change["field"])
            new_source.append(change.get("source", "cascaded"))
   
        snap_data["history"] = {
            "updatedOn": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "updatedBy": "xxx@amd.com",
            "from": new_from,
            "to": new_to,
            "valueField": new_field,
            "source": new_source
        }
   
        # 7. Final Acceptance Transition & Consistency Sync
        if is_fully_resolved:
            snap_data["standardization_status"] = "ACCEPTED"
           
            # --- FINAL CONSISTENCY SYNC (Double-Sync driven by History) ---
            ei_doc = await db[EXECUTION_INFO_COL].find_one({"benchmarkExecutionID": req.execution_id})
           
            if ei_doc:
                # Build a lookup for mappings from the current snapshot structure
                mapping_lookup = {}
                for item in invalid_values:
                    field_name = item.get("field")
                    if field_name:
                        mapping_lookup[field_name] = item.get("mapping")
                    for meta in item.get("metadata", []):
                        meta_name = meta.get("name")
                        if meta_name:
                            mapping_lookup[meta_name] = meta.get("mapping")
               
                # Sync ALL fields currently present in the final history to Executioninfo
                final_updates_applied = False
                for i, field_name in enumerate(new_field):
                    m_path = mapping_lookup.get(field_name)
                    m_val = new_to[i] if i < len(new_to) else None
                   
                    if m_path and m_val is not None:
                        final_updates_applied = True
                        # A. Update Flattened literal key
                        if m_path in ei_doc:
                            ei_doc[m_path] = m_val
                        # B. Update Nested Path
                        _set_nested_key(ei_doc, m_path, m_val)
               
                if final_updates_applied:
                    print(f"Applying Final History-Driven Double-Sync for {req.execution_id}")
                    await db[EXECUTION_INFO_COL].replace_one(
                        {"_id": ei_doc["_id"]},
                        ei_doc
                    )
        else:
            # Keep as PENDING if not all fields are resolved
            snap_data["standardization_status"] = "PENDING"
   
        # 7. Update Executioninfo with latest results
        # Recalculate remaining invalid fields for the summary
        current_invalid_fields = sorted(list(set(
            [p.get("field") for p in invalid_values if p.get("validation_status") != "valid"] +
            [m.get("name") for p in invalid_values for m in p.get("metadata", []) if m.get("validation_status") != "valid"]
        )))
       
        update_fields = {
            "isValid": is_fully_resolved,
            "invalidFields": current_invalid_fields,
            "lastModifiedOn": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        }
       
        # If fully resolved, ensure we clean up legacy fields
        unset_fields = {}
        if is_fully_resolved:
            unset_fields = {
                "validated": "",
                "standardized": "",
                "fieldStatus": "",
                "invalidPayload": ""
            }
           
        await db[EXECUTION_INFO_COL].update_one(
            {"benchmarkExecutionID": req.execution_id},
            {"$set": update_fields, "$unset": unset_fields}
        )
       
        # 8. Save entire Snapshot back
        await db[SNAPSHOT_COL].replace_one({"execution_id": req.execution_id}, snap)
       
        return {
            "status": "success",
            "message": f"Successfully {'accepted suggestion' if value_source == 'suggestion' else 'applied custom value'} for '{req.field_name}' and updated Executioninfo.",
            "execution_id": req.execution_id,
            "updated_field": req.field_name,
            "accepted_value": req.accepted_value,
            "mapping_path": target_mapping,
            "value_source": value_source
        }
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"CRITICAL ERROR in approve_suggestion: {str(e)}\n{error_details}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
                "type": type(e).__name__,
                "stacktrace": error_details
            }
        )
 

@router.put("/reject-record")
async def reject_record(req: RejectRecordRequest):
    """
    Manually rejects an entire record that cannot be standardized.
    Marks all suggestions as 'Rejected' and sets the standardization status to 'REJECTED'.
    The record remains 'isValid: False' in the source collection.
    """
    db = get_db()
    execution_id = req.execution_id
    
    # 1. Fetch Snapshot
    snap = await db[SNAPSHOT_COL].find_one({"execution_id": execution_id})
    if not snap or not snap.get("data"):
        return {"status": "error", "message": f"Snapshot not found for Execution ID: {execution_id}"}
    
    snap_data = snap["data"][0]
    invalid_values = snap_data.get("invalidValues", [])
    
    for item in invalid_values:
        item["currentStatus"] = req.currentStatus
        
        # Reject primary suggestions
        for sug in item.get("comparingData", []):
            sug["status"] = "Rejected"
            
        # Reject metadata suggestions
        for meta in item.get("metadata", []):
            for sug in meta.get("comparingData", []):
                sug["status"] = "Rejected"
    
    # 3. Transition Standardization Status
    snap_data["standardization_status"] = "REJECTED"
    snap_data["reason"] = "L0 Junk Data."
    
    # 4. Update Snapshot Timestamp (Keeping the old History as is)
    snap_data["lastModifiedOn"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    
    # 5. Update Executioninfo to include the entitliment_level
    await db[EXECUTION_INFO_COL].update_one(
        {"benchmarkExecutionID": execution_id},
        {"$set": {
            "entitliment_level": "L0 Junk Data.",
            "lastModifiedOn": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        }}
    )

    # 6. Save Snapshot
    await db[SNAPSHOT_COL].replace_one({"execution_id": execution_id}, snap)
    
    # Broadcast update
    await manager.broadcast({
        "type": "PIPELINE_UPDATE",
        "execution_id": execution_id,
        "stage": "standardization completed",
        "status": "REJECTED",
        "invalidFields": [],
        "benchmarkType": snap.get("benchmark_type"),
        "benchmarkCategory": snap.get("benchmark_category"),
        "updatedOn": snap["data"][0]["history"].get("updatedOn"),
        "suggestionsCount": False
    })
    await broadcast_summary(db)
    
    return {
        "status": "success",
        "message": f"Execution ID: {execution_id} has been manually REJECTED. All fuzzy suggestions have been cleared.",
        "execution_id": execution_id,
        "standardization_status": "REJECTED"
    }


@router.get("/draft-executions")
async def get_draft_executions():
    """
    Queries the collection where status=Draft and returns only the IDs.
    """
    db = get_db()
    
    # 1. Fetch all Draft masterlist records
    cursor = db[MASTERLIST_COL].find({"status": "Draft"})
    draft_docs = await cursor.to_list(None)
    
    exec_ids = []
    for d in draft_docs:
        # Extract the UUID. It might be stored as `_id` due to a typo in the DB creation script,
        # or it might be in execution_id. Fall back to the MongoDB _id.
        if "`_id`" in d:
            exec_ids.append(d["`_id`"])
        elif "execution_id" in d:
            exec_ids.append(d["execution_id"])
        else:
            exec_ids.append(str(d["_id"]))
            
    return exec_ids

@router.post("/draft-records/{type_name}")
async def create_masterlist_draft(type_name: str, draft: DraftRecordRequest):
    """
    Unified endpoint to add a new masterlist record to "In Review" status.
    Now fully dynamic: discovers schema and mappings from existing masterlist records.
    """
    db = get_db()
    
    # 1. Discover Schema and Resolve Actual Type
    schema = await get_dynamic_draft_fields(type_name)
    actual_type = schema["actual_type"]
    
    value = draft.value
    if not value:
        raise HTTPException(status_code=400, detail="The 'value' field is required in the request body.")
        
    # 2. Merge Metadata (Backward Compatible Fields + New metadata dict)
    incoming_metadata = draft.get_merged_metadata()
    
    # 3. Construct Metadata Filters for Composite Uniqueness
    # We only filter by metadata fields that are actually defined in the schema
    metadata_filters = {}
    for f in schema["metadata_fields"]:
        if f == "value": continue
        if f in incoming_metadata:
            metadata_filters[f] = incoming_metadata[f]

    existing = await _check_duplicate(db, actual_type, value, metadata_filters)
    if existing:
        # Build a descriptive error message showing the combination
        combination_str = f"'{value}'"
        if metadata_filters:
            meta_details = ", ".join([f"{k}: '{v}'" for k, v in metadata_filters.items()])
            combination_str += f" with metadata ({meta_details})"
            
        return {
            "status": "error",
            "message": f"A record for {actual_type} {combination_str} already exists in the masterlist (Status: {existing['status']})."
        }
        
    # 4. Build data content dynamically using template structure
    data_content = {
        "value": value,
        "mapping": schema.get("mapping")
    }
    
    # Optional sutType info from template
    if schema.get("sutType"):
        data_content["sutType"] = schema["sutType"]
    if schema.get("mapping_sutType"):
        data_content["mapping_sutType"] = schema["mapping_sutType"]
    
    # Populate Metadata
    metadata_obj = {}
    for f_name in schema["metadata_fields"]:
        if f_name == "value": continue
        
        # Get value from incoming request (Case-insensitive check)
        # 1. Try exact match (e.g., 'Family')
        # 2. Try lowercase match (e.g., 'family')
        f_val = incoming_metadata.get(f_name)
        if f_val is None:
            f_val = incoming_metadata.get(f_name.lower(), "")
            
        metadata_obj[f_name] = f_val
        
        # Get mapping from schema
        m_path = schema["metadata_mappings"].get(f_name)
        if m_path:
            metadata_obj[f"mapping_{f_name}"] = m_path
            
    data_content["metadata"] = metadata_obj
        
    # 5. Final Document Construction (Type before Status, Data before History)
    ml_doc = _build_base_ml_doc(actual_type, data_content, "", execution_id=draft.execution_id)
    
    await db[MASTERLIST_COL].insert_one(ml_doc)
    
    # 6. Place snapshots containing this drafted value "On Hold"
    update_filter = {"execution_id": draft.execution_id} if draft.execution_id else {"data.invalidValues.value": value}
    
    await db[SNAPSHOT_COL].update_many(
        update_filter,
        {"$set": {
            "data.0.standardization_status": "ON HOLD",
            "data.0.reason": "New Masterlist Draft Record.",
            "data.0.invalidValues.$[elem].currentStatus": "ON HOLD",
            "data.0.history.updatedOn": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        }},
        array_filters=[{"elem.field": {"$regex": f"^{actual_type}$", "$options": "i"}}]
    )
    
    # 7. Update lastModifiedOn in ExecutionInfo for consistency
    ei_filter = {"benchmarkExecutionID": draft.execution_id} if draft.execution_id else {}
    if ei_filter:
        await db[EXECUTION_INFO_COL].update_one(
            ei_filter,
            {"$set": {"lastModifiedOn": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")}}
        )
    
    return {
        "status": "success",
        "message": f"Successfully drafted {actual_type} record to masterlist with 'In Review' status. Affected snapshots placed 'On Hold'.",
        "id": ml_doc["`_id`"],
        "record_id": ml_doc["`_id`"],
        "execution_id": draft.execution_id or "Multiple"
    }

@router.get("/draft-records/fields")
async def get_draft_record_fields(type: str = Query(..., description="Record type: cpumodel, instancetype, or any other masterlist type")):
    """
    Returns the list of required field names for a given record type by checking the DB.
    """
    schema = await get_dynamic_draft_fields(type)
    
    # Transform list of strings into list of objects with fieldname and datatype
    fields_with_types = []
    for f_name in schema["metadata_fields"]:
        fields_with_types.append({
            "fieldname": f_name,
            "datatype": schema["field_types"].get(f_name, "string")
        })
        
    return {
        "status": "success",
        "type": schema["actual_type"],
        "fields": fields_with_types
    }

@router.post("/upload-execution-data")
async def upload_execution_data(file: UploadFile = File(...)):
    """
    Receives a JSON file, parses it, assigns each record a new UUID as benchmarkExecutionID,
    and inserts them into ExecutionInfo.
    """
    try:
        content = await file.read()
        data = json.loads(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON file: {str(e)}")
 
    if isinstance(data, dict):
        records = [data]
    elif isinstance(data, list):
        records = data
    else:
        raise HTTPException(status_code=400, detail="JSON must be an object or a list of objects")
 
    if not records:
        raise HTTPException(status_code=400, detail="No records found in file")
   
    # Assign a new UUID to every record to ensure uniqueness
    for rec in records:
        if not isinstance(rec, dict):
             raise HTTPException(status_code=400, detail="All records must be JSON objects")
        # Only assign a new UUID if the record doesn't already have one
        if not rec.get("benchmarkExecutionID"):
            rec["benchmarkExecutionID"] = str(uuid.uuid4())
   
    db = get_db()
    try:
        result = await db[EXECUTION_INFO_COL].insert_many(records)
        
        # Mark ALL uploaded records as "validation initiated" so the UI
        # immediately shows them as queued for processing
        await db[EXECUTION_INFO_COL].update_many(
            {"_id": {"$in": result.inserted_ids}},
            {"$set": {"stage": "validation initiated", "lastModifiedOn": datetime.utcnow().isoformat()}}
        )
        
        # Broadcast the updated summary so the dashboard reflects the new records instantly
        await broadcast_summary(db)
        
        return {
            "status": "success",
            "message": f"Successfully ingested {len(result.inserted_ids)} records",
            "total_records": len(result.inserted_ids),
            "execution_ids": [r["benchmarkExecutionID"] for r in records]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database insertion failed: {str(e)}")
