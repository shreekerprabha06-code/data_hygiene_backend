"""
Summary & Dashboard Routes
Handles: /invalid-summary, /summary-poll, /invalid-summary/batch, /validation-counts
"""
from fastapi import APIRouter, Query, HTTPException, Depends
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import time
import asyncio
from app.core.database import get_db, MASTERLIST_COL, EXECUTION_INFO_COL, SNAPSHOT_COL
from app.services.validation import build_mappings
from app.services.pipeline import get_current_summary
from app.services.helpers import (
    resolve_fuzzy_benchmarks, get_dynamic_age_counts,
    _get_dynamic_field_map, _report_cache, CACHE_TTL, get_current_user,
    build_expertise_query_filter
)

router = APIRouter()


@router.get("/invalid-summary")
async def get_invalid_summary(
    search: Optional[str] = Query(None, description="Search by Execution ID, Benchmark Type, or Category"),
    status: Optional[str] = Query(None, description="Filter by business status: PENDING, REJECTED, ACCEPTED, 'On Hold'"),
    stage: Optional[str] = Query(None, description="Filter by pipeline stage: VALIDATION_INPROGRESS, STANDARDIZATION_COMPLETED, etc."),
    age: Optional[str] = Query(None, description="Filter by age: green, yellow, or red"),
    page: int = Query(1, ge=1), 
    size: int = Query(50, ge=1, le=500),
    assigned_only: Optional[str] = Query(None, description="If 'true', only returns records assigned to the logged-in user"),
    user: dict = Depends(get_current_user)
):
    """
    Returns strictly the Execution_id and the names of the specific fields that are invalid.
    Optimized: Now queries the 'snapshot' collection directly for sub-second performance.
    """
    db = get_db()
    
    # 1. Search Filter (applies to all queries)
    final_search_filters = []
    
    role = user.get("role", "").upper()
    is_assigned_only = str(assigned_only).lower() == "true"
    
    if role == "SME":
        expert_cats = user.get("benchmarkCategories", user.get("expertise", []))
        exp_filter = await build_expertise_query_filter(expert_cats, db, username=user.get("username"), assigned_only=is_assigned_only)
        if exp_filter:
            final_search_filters.append(exp_filter)
    elif role == "ADMIN" and is_assigned_only:
        assignee_matches = []
        u_name = user.get("username")
        u_email = user.get("email")
        if u_name:
            assignee_matches.extend([{"tester": u_name}, {"assignment.assigned_sme": u_name}])
        if u_email:
            assignee_matches.extend([{"tester": u_email}, {"assignment.assigned_sme": u_email}])
        if assignee_matches:
            final_search_filters.append({"$or": assignee_matches})
            
    if search:
        # Optimization: If search looks like a full UUID, do an exact match first (super fast)
        is_uuid = len(search) == 36 and search.count("-") == 4
        
        if is_uuid:
            final_search_filters.append({"benchmarkExecutionID": search})
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
                cat_val = resolved["benchmarkCategory"]
                if resolved.get("benchmarkCategory_is_fuzzy"):
                    or_filters.append({"benchmarkCategory": cat_val})
                else:
                    or_filters.append({"benchmarkCategory": search_regex})
                   
            if len(or_filters) == 1:
                or_filters.extend([
                    {"benchmarkType": search_regex},
                    {"benchmarkCategory": search_regex}
                ])
               
            final_search_filters.append({"$or": or_filters})

    search_query = {}
    if len(final_search_filters) > 1:
        search_query = {"$and": final_search_filters}
    elif len(final_search_filters) == 1:
        search_query = final_search_filters[0]

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
                "tester": doc.get("tester") or doc.get("assignment", {}).get("assigned_sme", ""),
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
            _cached = await db["SystemCache"].find_one({"_id": "LAST_SUMMARY"}) or {}
            return {"red": _cached.get("red", 0), "yellow": _cached.get("yellow", 0), "green": _cached.get("green", 0)}
        else:
            age_search_query = {}
            if "benchmarkCategory" in search_query:
                age_search_query["benchmarkCategory"] = search_query["benchmarkCategory"]
                
            if search:
                is_uuid = len(search) == 36 and search.count("-") == 4
                if is_uuid: 
                    age_search_query["benchmarkExecutionID"] = search
                else: 
                    age_search_query["$or"] = [
                        {"benchmarkExecutionID": {"$regex": search, "$options": "i"}},
                        {"benchmarkType": {"$regex": search, "$options": "i"}},
                        {"benchmarkCategory": {"$regex": search, "$options": "i"}}
                    ]
            return await get_dynamic_age_counts(db, age_search_query)

    async def _fetch_stage_counts():
        _cached = await db["SystemCache"].find_one({"_id": "LAST_SUMMARY"}) or {}
        return {
            "VALIDATION_INITIATED": _cached.get("VALIDATION_INITIATED", 0),
            "VALIDATION_IN_PROGRESS": _cached.get("VALIDATION_IN_PROGRESS", 0),
            "VALIDATION_COMPLETED": _cached.get("VALIDATION_COMPLETED", 0),
            "STANDARDIZATION_IN_PROGRESS": _cached.get("STANDARDIZATION_IN_PROGRESS", 0),
            "STANDARDIZATION_COMPLETED": _cached.get("STANDARDIZATION_COMPLETED", 0),
        }


    async def _fetch_status_counts():
        _cached = await db["SystemCache"].find_one({"_id": "LAST_SUMMARY"}) or {}
        return {
            "PENDING": _cached.get("PENDING", 0),
            "REJECTED": _cached.get("REJECTED", 0),
            "ACCEPTED": _cached.get("ACCEPTED", 0),
            "ON HOLD": _cached.get("ON HOLD", 0),
            "N/A": _cached.get("N/A", 0)
        }

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
