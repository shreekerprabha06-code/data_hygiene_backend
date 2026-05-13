"""
Snapshot & Record Detail Routes
Handles: /snapshot-records/{id}, /metadata-values/{type}/{value}, /unique-values, /search-snapshots
"""
from fastapi import APIRouter, Query, HTTPException, Depends
from typing import Optional, List, Dict, Any
from datetime import datetime
import asyncio
from pydantic import BaseModel
from app.core.database import get_db, MASTERLIST_COL, EXECUTION_INFO_COL, SNAPSHOT_COL
from app.services.validation import build_mappings, get_validator
from app.services.helpers import (
    get_masterlist_mappings, resolve_fuzzy_benchmarks, get_masterlist_values,
    _get_dynamic_field_map, _get_masterlist_all_unique_values, get_current_user,
    build_expertise_query_filter
)

router = APIRouter()


@router.get("/snapshot-records/{Execution_id}")
async def get_snapshot_records(Execution_id: str, user: dict = Depends(get_current_user)):
    """
    Fetches a specific record from the snapshot collection by Execution_id (Path Parameter).
    Flattens invalid metadata into a simple Data array with mappings.
    """
    db = get_db()
    Execution_id = Execution_id.strip()
    
    # Fetch metadata from ExecutionInfo
    exec_meta = await db[EXECUTION_INFO_COL].find_one({"benchmarkExecutionID": Execution_id})
    if not exec_meta:
        exec_meta = {}
        
    # Enforce domain expertise restriction: SMEs are restricted, Admins bypass
    if user.get("role", "").upper() == "SME":
        expert_cats = user.get("benchmarkCategories", user.get("expertise", []))
        exp_filter = await build_expertise_query_filter(expert_cats, db)
        if exp_filter:
            allowed_record = await db[EXECUTION_INFO_COL].find_one({
                "benchmarkExecutionID": Execution_id,
                **exp_filter
            })
            if not allowed_record:
                raise HTTPException(
                    status_code=403,
                    detail=f"Access Denied: You do not have registered expertise to view this record."
                )
            
    doc = await db[SNAPSHOT_COL].find_one({"execution_id": Execution_id})
    
    if not doc or not doc.get("data"):
        return {
            "status": "error",
            "message": f"No snapshot record found for Execution_id: {Execution_id}"
        }

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
            "tester":            exec_meta.get("tester") or (exec_meta.get("assignment") or {}).get("assigned_sme", ""),
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


@router.get("/metadata-values/{type_name}/{value}")
async def get_metadata_for_value(type_name: str, value: str):
    """
    Given a primary field type (e.g. 'CPUModel') and a selected value (e.g. '7543'),
    returns all metadata configurations associated with that value from the masterlist,
    along with their mapping paths.
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


@router.get("/search-snapshots")
async def search_snapshots(
    status: str = Query("PENDING", description="Filter by status: PENDING, REJECTED, ACCEPTED, 'On Hold'"),
    benchmarkType: Optional[str] = Query(None),
    benchmarkCategory: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    assigned_only: Optional[str] = Query(None, description="If 'true', only returns records assigned to the logged-in user"),
    user: dict = Depends(get_current_user)
):
    db = get_db()
    
    # Fuzzy resolution
    resolved = await resolve_fuzzy_benchmarks(benchmarkType, benchmarkCategory)
    
    # 1. First, search ExecutionInfo to get the IDs of benchmarks that match
    final_exec_filters = []
    
    role = user.get("role", "").upper()
    is_assigned_only = str(assigned_only).lower() == "true"
    
    if role == "SME":
        expert_cats = user.get("benchmarkCategories", user.get("expertise", []))
        exp_filter = await build_expertise_query_filter(expert_cats, db, username=user.get("username"), assigned_only=is_assigned_only)
        if exp_filter:
            final_exec_filters.append(exp_filter)
    elif role == "ADMIN" and is_assigned_only:
        assignee_matches = []
        u_name = user.get("username")
        u_email = user.get("email")
        if u_name:
            assignee_matches.extend([{"tester": u_name}, {"assignment.assigned_sme": u_name}])
        if u_email:
            assignee_matches.extend([{"tester": u_email}, {"assignment.assigned_sme": u_email}])
        if assignee_matches:
            final_exec_filters.append({"$or": assignee_matches})
            
    # Add resolved filters for individual benchmarkType / benchmarkCategory parameters
    if benchmarkType or benchmarkCategory:
        resolved_filter = {}
        if "benchmarkType" in resolved:
            if resolved.get("benchmarkType_is_fuzzy"):
                resolved_filter["benchmarkType"] = resolved["benchmarkType"]
            else:
                resolved_filter["benchmarkType"] = {"$regex": resolved["benchmarkType"], "$options": "i"}
                
        if "benchmarkCategory" in resolved:
            cat_val = resolved["benchmarkCategory"]
            if resolved.get("benchmarkCategory_is_fuzzy"):
                resolved_filter["benchmarkCategory"] = cat_val
            else:
                resolved_filter["benchmarkCategory"] = {"$regex": cat_val, "$options": "i"}
        if resolved_filter:
            final_exec_filters.append(resolved_filter)

    if search:
        search_regex = {"$regex": search, "$options": "i"}
        # Fuzzy resolution for both Type and Category
        resolved_search = await resolve_fuzzy_benchmarks(benchmarkType=search, benchmarkCategory=search)
        or_filters = [{"benchmarkExecutionID": search_regex}]
        
        if "benchmarkType" in resolved_search:
            if resolved_search.get("benchmarkType_is_fuzzy"):
                or_filters.append({"benchmarkType": resolved_search["benchmarkType"]})
            else:
                or_filters.append({"benchmarkType": search_regex})
        
        if "benchmarkCategory" in resolved_search:
            cat_val = resolved_search["benchmarkCategory"]
            if resolved_search.get("benchmarkCategory_is_fuzzy"):
                or_filters.append({"benchmarkCategory": cat_val})
            else:
                or_filters.append({"benchmarkCategory": search_regex})
        
        # Always fallback to general regex on all three if no fuzzy matches found yet
        if len(or_filters) == 1:
            or_filters.extend([
                {"benchmarkType": search_regex},
                {"benchmarkCategory": search_regex}
            ])
            
        final_exec_filters.append({"$or": or_filters})

    exec_query = {}
    if len(final_exec_filters) > 1:
        exec_query = {"$and": final_exec_filters}
    elif len(final_exec_filters) == 1:
        exec_query = final_exec_filters[0]

    if not exec_query:
        return {"status": "success", "data": [], "message": "No search parameters provided."}

    # Get matching IDs
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


