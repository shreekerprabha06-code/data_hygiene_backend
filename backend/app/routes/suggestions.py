"""
Suggestion & Rejection Routes
Handles: /approve-suggestion, /reject-record
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from datetime import datetime
from app.core.database import get_db, MASTERLIST_COL, EXECUTION_INFO_COL, SNAPSHOT_COL
from app.schemas.models import ApproveSuggestionRequest, RejectRecordRequest
from app.services.ws_manager import manager
from app.services.helpers import (
    get_masterlist_mappings, broadcast_summary, _set_nested_key
)

router = APIRouter()


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
