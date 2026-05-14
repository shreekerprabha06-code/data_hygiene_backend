"""
Draft & Upload Routes
Handles: /draft-executions, /draft-records/{type_name}, /draft-records/fields, /upload-execution-data
"""
from fastapi import APIRouter, Query, HTTPException, File, UploadFile, Depends
from typing import Dict, Any
from datetime import datetime
import json
import uuid
from app.core.database import get_db, MASTERLIST_COL, EXECUTION_INFO_COL, SNAPSHOT_COL
from app.schemas.models import DraftRecordRequest
from app.services.helpers import (
    _check_duplicate, _build_base_ml_doc, get_dynamic_draft_fields, broadcast_summary,
    get_current_user, auto_assign_records
)

router = APIRouter()


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
async def create_masterlist_draft(type_name: str, draft: DraftRecordRequest, user: dict = Depends(get_current_user)):
    """
    Unified endpoint to add a new masterlist record to "In Review" status.
    Now fully dynamic: discovers schema and mappings from existing masterlist records.
    """
    db = get_db()
    
    # Enforce SME assignment restriction: SMEs can only edit/draft on records assigned strictly to them
    if user.get("role") == "SME":
        exec_id = draft.execution_id
        if exec_id:
            record = await db[EXECUTION_INFO_COL].find_one({"benchmarkExecutionID": exec_id})
            if record:
                assigned_sme = record.get("assignment", {}).get("assigned_sme")
                if assigned_sme != user.get("username"):
                    raise HTTPException(
                        status_code=403,
                        detail=f"Access Denied: Record {exec_id} is not assigned to you."
                    )
    
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
async def upload_execution_data(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
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
        
        # Trigger automatic workload assignment to expert SMEs
        await auto_assign_records(db, result.inserted_ids)
        
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
