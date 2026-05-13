import asyncio
import os
import uuid
import logging
import time
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import PyMongoError, OperationFailure
from dotenv import load_dotenv
from app.core.database import get_db, close_db, EXECUTION_INFO_COL, SNAPSHOT_COL
from app.services.validation import get_validator
from app.services.ws_manager import manager
 
# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)
 
load_dotenv()
 
# Fields that should NOT trigger a re-validation when updated (Internal statuses)
INTERNAL_FIELDS = {
    "stage", "isValid",
    "fieldStatus", "invalidPayload", "invalidFields", "lastModifiedOn",
    "benchmarkExecutionID",
    # Legacy fields that get $unset during pipeline transitions
    "validated", "standardized", "validation", "standardization"
}
 
# Global cache for the last calculated summary to avoid redundant DB aggregation
_LAST_SUMMARY = {
    "PENDING": 0, "REJECTED": 0, "ACCEPTED": 0, "ON HOLD": 0, "N/A": 0,
    "VALIDATION_INITIATED": 0, "VALIDATION_IN_PROGRESS": 0,
    "STANDARDIZATION_IN_PROGRESS": 0, "STANDARDIZATION_COMPLETED": 0,
    "red": 0, "yellow": 0, "green": 0
}
_SUMMARY_LOCK = asyncio.Lock()
 
async def get_current_summary(db):
    """Calculates and returns the global summary counts using a single optimized pass."""
    now = datetime.now(timezone.utc)
    green_threshold = (now - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    yellow_threshold = (now - timedelta(days=6)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
 
    pipeline = [
        {"$match": {"stage": {"$exists": True}}},
        {"$lookup": {
            "from": SNAPSHOT_COL,
            "localField": "benchmarkExecutionID",
            "foreignField": "execution_id",
            "pipeline": [{"$project": {"data.standardization_status": 1}}],
            "as": "snapshot"
        }},
        {"$unwind": {"path": "$snapshot", "preserveNullAndEmptyArrays": True}},
        {"$facet": {
            "statuses": [
                {"$project": {
                    "status": {
                        "$cond": {
                            "if": {"$ne": ["$stage", "standardization completed"]},
                            "then": "N/A",
                            "else": {
                                "$cond": {
                                    "if": {"$and": [{"$isArray": "$snapshot.data"}, {"$gt": [{"$size": "$snapshot.data"}, 0]}]},
                                    "then": {"$arrayElemAt": ["$snapshot.data.standardization_status", 0]},
                                    "else": "PENDING"
                                }
                            }
                        }
                    }
                }},
                {"$group": {"_id": "$status", "count": {"$sum": 1}}}
            ],
            "stages": [
                {"$group": {"_id": "$stage", "count": {"$sum": 1}}}
            ],
            "age": [
                {"$match": {"lastModifiedOn": {"$type": "string"}}},
                {"$group": {
                    "_id": {
                        "$cond": [
                            {"$gte": ["$lastModifiedOn", green_threshold]}, "green",
                            {"$cond": [{"$gte": ["$lastModifiedOn", yellow_threshold]}, "yellow", "red"]}
                        ]
                    },
                    "count": {"$sum": 1}
                }}
            ]
        }}
    ]
   
    agg_results = await db[EXECUTION_INFO_COL].aggregate(pipeline).to_list(1)
    facet_res = agg_results[0] if agg_results else {"statuses": [], "stages": [], "age": []}
 
    # Parse Status Counts
    status_counts = {"PENDING": 0, "REJECTED": 0, "ACCEPTED": 0, "ON HOLD": 0, "N/A": 0}
    for s in facet_res["statuses"]:
        key = str(s["_id"] or "N/A").upper()
        if key in status_counts: status_counts[key] = s["count"]
        else: status_counts["N/A"] += s["count"]
 
    # Parse Stage Counts
    raw_stages = {str(s["_id"] or "unknown").lower(): s["count"] for s in facet_res["stages"]}
    grouped_stages = {
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
        "TOTAL_INVALID_RECORDS": (
            raw_stages.get("validation initiated", 0) +
            raw_stages.get("validation inprogress", 0) +
            raw_stages.get("validation completed", 0) +
            raw_stages.get("validation failed", 0) +
            raw_stages.get("standardization inprogress", 0) +
            raw_stages.get("standardization failed", 0)
        )
    }
 
    # Parse Age Counts
    age_counts = {"red": 0, "yellow": 0, "green": 0}
    for a in facet_res.get("age", []):
        if a["_id"] in age_counts:
            age_counts[a["_id"]] = a["count"]
 
    return {**status_counts, **grouped_stages, **age_counts}
 
async def broadcast_summary(db):
    """Calculates and broadcasts global summary counts."""
    global _LAST_SUMMARY
    summary = await get_current_summary(db)
   
    async with _SUMMARY_LOCK:
        _LAST_SUMMARY = summary
        
    # Save cache to DB for other microservices to read instantly
    await db["SystemCache"].replace_one(
        {"_id": "LAST_SUMMARY"},
        summary,
        upsert=True
    )
 
    await manager.broadcast({
        "type": "PIPELINE_UPDATE",
        "summary": summary
    })
 
 
# ============================================================================
# PIPELINE 1: VALIDATION
# Polls for unvalidated records, validates against masterlist, updates ExecutionInfo
# ============================================================================
 
async def validate_document(db, validator, doc):
    """
    Pipeline 1: Validates a single document against the masterlist.
    Sets: isValid, invalidPayload, fieldStatus, validated status on ExecutionInfo.
    Status flow: (none) -> "In Progress" -> "Completed" / "Failed"
    """
    try:
        exec_id = doc.get("benchmarkExecutionID")
        if not exec_id:
            exec_id = str(uuid.uuid4())
 
        # Mark as In Progress and remove legacy fields
        await db[EXECUTION_INFO_COL].update_one(
            {"_id": doc["_id"]},
            {
                "$set": {
                    "benchmarkExecutionID": exec_id,
                    "stage": "validation inprogress"
                },
                "$unset": {"validated": "", "standardized": "", "fieldStatus": "", "invalidPayload": "", "validation": "", "standardization": ""}
            }
        )
       
        await asyncio.sleep(0.5)  # 500ms yield
 
        # Run Validation against masterlist
        invalid_payload, field_status = await validator.validate_doc(db, doc)
        is_val = len(invalid_payload) == 0
 
        # Update ExecutionInfo with validation result
        # Extract all field names that are in the invalid payload
        invalid_fields = sorted(list(set([p.get("field") for p in invalid_payload])))
       
        await db[EXECUTION_INFO_COL].update_one(
            {"_id": doc["_id"]},
            {
                "$set": {
                    "invalidPayload": invalid_payload,
                    "invalidFields": invalid_fields, # Lightweight list for dashboard
                    "isValid": is_val,
                    "stage": "validation completed",
                    "fieldStatus": field_status,
                    "lastModifiedOn": datetime.now(timezone.utc).isoformat()
                }
            }
        )
 
        status_str = "VALID" if is_val else f"INVALID ({len(invalid_payload)} error groups)"
        logger.info(f"[Validation] COMPLETED: {exec_id} | {status_str}")
 
        # Broadcast update to UI (Combined with latest summary)
        await manager.broadcast({
            "type": "PIPELINE_UPDATE",
            "execution_id": exec_id,
            "stage": "validation completed",
            "isValid": is_val,
            "invalidFields": invalid_fields,
            "benchmarkType": doc.get("benchmarkType"),
            "benchmarkCategory": doc.get("benchmarkCategory"),
            "updatedOn": datetime.now(timezone.utc).isoformat(),
            "suggestionsCount": False, # No suggestions until standardization
            "summary": _LAST_SUMMARY
        })
 
    except Exception as e:
        # Mark as Failed so it can be retried
        await db[EXECUTION_INFO_COL].update_one(
            {"_id": doc["_id"]},
            {"$set": {"stage": "validation failed"}}
        )
        logger.error(f"[Validation] FAILED: {doc.get('_id')} | {str(e)}")
 
 
async def validate_document_only(db, validator, doc):
    """Validates a single document that has ALREADY been marked as 'validation inprogress'.
    Used by the batch pipeline where the batch marks all records first."""
    try:
        exec_id = doc.get("benchmarkExecutionID")
 
        # Run Validation against masterlist
        invalid_payload, field_status = await validator.validate_doc(db, doc)
        is_val = len(invalid_payload) == 0
 
        # Extract all field names that are in the invalid payload
        invalid_fields = sorted(list(set([p.get("field") for p in invalid_payload])))
       
        await db[EXECUTION_INFO_COL].update_one(
            {"_id": doc["_id"]},
            {
                "$set": {
                    "invalidPayload": invalid_payload,
                    "invalidFields": invalid_fields,
                    "isValid": is_val,
                    "stage": "validation completed",
                    "fieldStatus": field_status,
                    "lastModifiedOn": datetime.now(timezone.utc).isoformat()
                }
            }
        )
 
        status_str = "VALID" if is_val else f"INVALID ({len(invalid_payload)} error groups)"
        logger.info(f"[Validation] COMPLETED: {exec_id} | {status_str}")
 
        # Broadcast update to UI
        await manager.broadcast({
            "type": "PIPELINE_UPDATE",
            "execution_id": exec_id,
            "stage": "validation completed",
            "isValid": is_val,
            "invalidFields": invalid_fields,
            "benchmarkType": doc.get("benchmarkType"),
            "benchmarkCategory": doc.get("benchmarkCategory"),
            "updatedOn": datetime.now(timezone.utc).isoformat(),
            "suggestionsCount": False,
            "summary": _LAST_SUMMARY
        })
 
    except Exception as e:
        await db[EXECUTION_INFO_COL].update_one(
            {"_id": doc["_id"]},
            {"$set": {"stage": "validation failed"}}
        )
        logger.error(f"[Validation] FAILED: {doc.get('_id')} | {str(e)}")
 
# ============================================================================
# PIPELINE 2: STANDARDIZATION
# Polls for validated-but-not-standardized records, creates/updates snapshots
# ============================================================================
 
async def standardize_document(db, validator, doc):
    """
    Pipeline 2: Creates/updates the snapshot for a validated document.
    Builds fuzzy suggestions and preserves history from existing snapshots.
    Sets: standardized=True on ExecutionInfo after snapshot is written.
    """
    try:
        exec_id = doc.get("benchmarkExecutionID")
        logger.info(f"[Standardization] IN_PROGRESS: {exec_id}")
       
        # Mark as In Progress in DB
        await db[EXECUTION_INFO_COL].update_one(
            {"_id": doc["_id"]},
            {"$set": {"stage": "standardization inprogress"}}
        )
       
        is_val = doc.get("isValid", False)
        invalid_payload = doc.get("invalidPayload", [])
 
        # Fetch existing snapshot (if any) for history preservation
        latest_snap = await db[SNAPSHOT_COL].find_one(
            {"execution_id": exec_id},
            {"data": {"$slice": 1}, "snapshot_id": 1}
        )
 
        if is_val:
            # Record is VALID - Only update if a snapshot ALREADY exists (History Preservation)
            if latest_snap and latest_snap.get("data"):
                prev_data = latest_snap["data"][0]
                current_status = str(prev_data.get("standardization_status", "")).upper()
                if current_status not in ["ACCEPTED", "REJECTED", "ON HOLD"]:
                    await db[SNAPSHOT_COL].update_one(
                        {"execution_id": exec_id},
                        {"$set": {
                            "data.0.standardization_status": "ACCEPTED",
                            "data.0.lastModifiedOn": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                        }}
                    )
            logger.info(f"[Standardization] COMPLETED: {exec_id} | Valid record preserved")
        else:
            # Record is INVALID - Create or Update Snapshot with fuzzy suggestions
            prev_data = {}
            snap_id = str(uuid.uuid4())
            if latest_snap:
                snap_id = latest_snap.get("snapshot_id", snap_id)
                if latest_snap.get("data"):
                    prev_data = latest_snap["data"][0]
 
            # Normalize status to uppercase, defaults to PENDING
            raw_status = prev_data.get("standardization_status", "PENDING")
            status_val = raw_status.upper() if raw_status else "PENDING"
 
            clean_meta = []
            for p in invalid_payload:
                field = p.get("field")
                val = p.get("value")
 
                p_clean = {
                    "field": field,
                    "currentStatus": "invalid",
                    "value": val,
                    "datatype": validator.field_types.get(field, "STRING").lower(),
                    "validation_status": p.get("validation_status", "invalid"),
                    "mapping": p.get("mapping", "")
                }
                actual_meta_vals = {m["name"]: m.get("value", "") for m in p.get("metadata", []) if m.get("name")}
 
                # Get record-level suggestions using 'Mega-String' fuzzy matching
                record_suggestions = validator.get_record_level_suggestions(field, val, actual_meta_vals)
 
                # Build formatted suggestions for the dashboard
                primary_comparing = []
                for i, rec_sug in enumerate(record_suggestions, 1):
                    primary_comparing.append({
                        f"suggestion{i}": rec_sug["primary_value"],
                        f"score{i}": rec_sug["score"],
                        "status": "PENDING",
                        "_id": rec_sug["_id"]
                    })
                p_clean["comparingData"] = primary_comparing
 
                meta_list = []
                for m in p.get("metadata", []):
                    m_clean = dict(m)
                    m_name = m_clean.get("name")
                    m_clean["datatype"] = validator.field_types.get(m_name, "STRING").lower()
                    m_comparing = []
                    for i, rec_sug in enumerate(record_suggestions, 1):
                        m_comparing.append({
                            f"suggestion{i}": rec_sug["metadata"].get(m_name, ""),
                            f"score{i}": rec_sug["score"],
                            "status": "PENDING",
                            "_id": rec_sug["_id"]
                        })
                    m_clean["comparingData"] = m_comparing
                    meta_list.append(m_clean)
                p_clean["metadata"] = meta_list
                clean_meta.append(p_clean)
 
            snapshot_doc = {
                "snapshot_id": snap_id,
                "execution_id": exec_id,
                "benchmark_type": doc.get("benchmarkType"),
                "benchmark_category": doc.get("benchmarkCategory"),
                "data": [{
                    "invalidFields": sorted(list(set(
                        [p.get("field") for p in clean_meta if p.get("validation_status") == "invalid"] +
                        [m.get("name") for p in clean_meta for m in p.get("metadata", []) if m.get("validation_status") == "invalid"]
                    ))),
                    "invalidValues": clean_meta,
                    "standardization_status": status_val,
                    "history": prev_data.get("history", {
                        "updatedOn": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                        "updatedBy": "xxx@amd.com",
                        "from": [], "to": [], "valueField": [], "source": []
                    })
                }]
            }
 
            await db[SNAPSHOT_COL].replace_one(
                {"execution_id": exec_id},
                snapshot_doc,
                upsert=True
            )
            logger.info(f"[Standardization] COMPLETED: {exec_id} | Snapshot created")
 
        # Mark as Completed and remove legacy/internal fields
        # IMPORTANT: This must happen BEFORE the broadcast to avoid race conditions
        # where the UI fetches the record before the DB is updated.
        # Fetch the assigned user's email ID
        assigned_sme = doc.get("assignment", {}).get("assigned_sme") or doc.get("tester")
        email_val = None
        if assigned_sme:
            user_doc = await db["users"].find_one({"username": assigned_sme})
            if user_doc:
                email_val = user_doc.get("email")

        # Mark as Completed and remove legacy/internal fields
        # IMPORTANT: This must happen BEFORE the broadcast to avoid race conditions
        # where the UI fetches the record before the DB is updated.
        set_payload = {
            "stage": "standardization completed",
            "lastModifiedOn": datetime.now(timezone.utc).isoformat()
        }
        if email_val:
            set_payload["tester"] = email_val

        await db[EXECUTION_INFO_COL].update_one(
            {"_id": doc["_id"]},
            {
                "$set": set_payload,
                "$unset": {
                    "validated": "",
                    "standardized": "",
                    "fieldStatus": "",
                    "invalidPayload": "",
                    "validation": "",
                    "standardization": ""
                }
            }
        )
 
        # Broadcast AFTER DB commit so the UI always reads the correct state
        if not is_val:
            await manager.broadcast({
                "type": "PIPELINE_UPDATE",
                "execution_id": exec_id,
                "stage": "standardization completed",
                "status": status_val,
                "invalidFields": snapshot_doc["data"][0]["invalidFields"],
                "benchmarkType": doc.get("benchmarkType"),
                "benchmarkCategory": doc.get("benchmarkCategory"),
                "updatedOn": snapshot_doc["data"][0]["history"].get("updatedOn"),
                "suggestionsCount": len(snapshot_doc["data"][0]["invalidFields"]) > 0,
                "summary": _LAST_SUMMARY
            })
 
    except Exception as e:
        # Mark as Failed so it can be retried
        await db[EXECUTION_INFO_COL].update_one(
            {"_id": doc["_id"]},
            {"$set": {"stage": "standardization failed"}}
        )
        logger.error(f"[Standardization] FAILED: {doc.get('_id')} | {str(e)}")
 
 
# ============================================================================
# PARALLEL PIPELINE RUNNERS
# ============================================================================
 
# Global timestamp to debounce broadcasts (prevent DB saturation)
LAST_BROADCAST_TIME = 0
BROADCAST_LOCK = asyncio.Lock()
 
async def debounced_broadcast(db):
    """Broadcasts summary at most once every 2 seconds."""
    global LAST_BROADCAST_TIME
    current_time = time.time()
   
    if current_time - LAST_BROADCAST_TIME > 2:
        async with BROADCAST_LOCK:
            # Double check inside lock
            if time.time() - LAST_BROADCAST_TIME > 2:
                await broadcast_summary(db)
                LAST_BROADCAST_TIME = time.time()
 
async def run_validation_pipeline(db, validator, collection_name, interval=1, batch_size=50):
    """Pipeline 1: Batch-Mark-Then-Process Validation.
   
    Picks up `batch_size` records at once, marks ALL of them as 'validation inprogress'
    so the UI can see the full batch, then processes them one by one.
    """
    logger.info(f"[VALIDATION PIPELINE] Started (Batch Size: {batch_size})")
    collection = db[collection_name]
 
    while True:
        try:
            query = {"stage": {"$in": ["validation initiated", "validation failed"]}}
           
            # 1. Pick up a batch of records that are queued for validation
            batch_docs = await collection.find(query).limit(batch_size).to_list(batch_size)
           
            if not batch_docs:
                await asyncio.sleep(interval)
                continue
           
            # 2. Mark ALL records in the batch as "validation inprogress" at once
            batch_ids = [doc["_id"] for doc in batch_docs]
            # Assign execution IDs to any docs missing them
            for doc in batch_docs:
                if not doc.get("benchmarkExecutionID"):
                    doc["benchmarkExecutionID"] = str(uuid.uuid4())
           
            await collection.update_many(
                {"_id": {"$in": batch_ids}},
                {
                    "$set": {"stage": "validation inprogress"},
                    "$unset": {"validated": "", "standardized": "", "fieldStatus": "", "invalidPayload": "", "validation": "", "standardization": ""}
                }
            )
            # Also set any generated execution IDs
            for doc in batch_docs:
                await collection.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"benchmarkExecutionID": doc.get("benchmarkExecutionID", str(uuid.uuid4()))}}
                )
           
            await debounced_broadcast(db)
            logger.info(f"[VALIDATION] Batch marked {len(batch_docs)} records as inprogress")
           
            # 3. Process them one by one
            for i, doc in enumerate(batch_docs):
                try:
                    await validate_document_only(db, validator, doc)
                    if i % 10 == 0:  # Broadcast every 10th record to reduce overhead
                        await debounced_broadcast(db)
                except Exception as e:
                    logger.error(f"[VALIDATION] Single doc error: {e}")
               
                await asyncio.sleep(0.5)  # 500ms yield
           
            # Force a final broadcast after each batch to ensure cache is up to date
            await broadcast_summary(db)
               
        except Exception as e:
            logger.error(f"[VALIDATION PIPELINE] Error: {e}")
            await asyncio.sleep(interval)
 
async def run_standardization_pipeline(db, validator, collection_name, interval=1, batch_size=50):
    """Pipeline 2: Batch-Mark-Then-Process Standardization.
   
    Picks up `batch_size` records at once, marks ALL of them as 'standardization inprogress'
    so the UI can see the full batch, then processes them one by one.
    """
    logger.info(f"[STANDARDIZATION PIPELINE] Started (Batch Size: {batch_size})")
    collection = db[collection_name]
 
    while True:
        try:
            # Poll for records that are ready for standardization OR previously failed
            query = {"stage": {"$in": ["validation completed", "standardization failed"]}}
           
            # 1. Pick up a batch of ready records
            batch_docs = await collection.find(query).limit(batch_size).to_list(batch_size)
           
            if not batch_docs:
                await asyncio.sleep(interval)
                continue
           
            # 2. Mark ALL records in the batch as "standardization inprogress" at once
            batch_ids = [doc["_id"] for doc in batch_docs]
            await collection.update_many(
                {"_id": {"$in": batch_ids}},
                {"$set": {"stage": "standardization inprogress"}}
            )
           
            await debounced_broadcast(db)
            logger.info(f"[STANDARDIZATION] Batch marked {len(batch_docs)} records as inprogress")
           
            # 3. Process them one by one
            for i, doc in enumerate(batch_docs):
                try:
                    await standardize_document(db, validator, doc)
                    if i % 10 == 0:  # Broadcast every 10th record to reduce overhead
                        await debounced_broadcast(db)
                except Exception as e:
                    logger.error(f"[STANDARDIZATION] Single doc error: {e}")
               
                await asyncio.sleep(0.5)  # 500ms yield
           
            # Force a final broadcast after each batch to ensure cache is up to date
            await broadcast_summary(db)
        except Exception as e:
            logger.error(f"[STANDARDIZATION PIPELINE] Error: {e}")
            await asyncio.sleep(interval)
 
 
# ============================================================================
# MAIN ENTRY POINT
# ============================================================================
 
async def run_trigger():
    """
    Main entry point. Launches both pipelines in parallel.
    Falls back to polling if Change Streams are not supported.
    """
    db = get_db()
    collection = db[EXECUTION_INFO_COL]
 
    # --- STARTUP CLEANUP ---
    # Any records stuck in 'inprogress' from a previous run should be reset
    # so the pipelines can pick them up again.
    logger.info("Cleaning up stale 'inprogress' records on startup...")
   
    # Validation In-Progress -> Back to "validation initiated" so the pipeline picks them up again
    val_reset = await collection.update_many(
        {"stage": "validation inprogress"},
        {"$set": {"stage": "validation initiated"}}
    )
    if val_reset.modified_count > 0:
        logger.info(f"Reset {val_reset.modified_count} stale validation records to 'validation initiated'.")
 
    # Standardization In-Progress -> Back to 'validation completed'
    std_reset = await collection.update_many(
        {"stage": "standardization inprogress"},
        {"$set": {"stage": "validation completed"}}
    )
    if std_reset.modified_count > 0:
        logger.info(f"Reset {std_reset.modified_count} stale standardization records.")
 
    # Records with NO stage at all (e.g. inserted directly into DB, not via upload API)
    # -> Set to "validation initiated" so the pipeline picks them up
    no_stage = await collection.update_many(
        {"stage": {"$exists": False}},
        {"$set": {"stage": "validation initiated", "lastModifiedOn": datetime.now(timezone.utc).isoformat()}}
    )
    if no_stage.modified_count > 0:
        logger.info(f"Found {no_stage.modified_count} records with no stage. Set to 'validation initiated'.")
 
    logger.info("Initializing Validator...")
    validator = await get_validator()
    logger.info("Validator ready.")
 
    # Populate the summary cache immediately so /invalid-summary returns correct counts
    await broadcast_summary(db)
    logger.info("Initial summary broadcast complete.")
 
    logger.info("Starting dual pipelines: Validation + Standardization (both polling)...")

    # Run BOTH pipelines in parallel using the reliable polling method
    # This guarantees no records are missed even if they were uploaded while the server was offline
    try:
        await asyncio.gather(
            run_validation_pipeline(db, validator, EXECUTION_INFO_COL),
            run_standardization_pipeline(db, validator, EXECUTION_INFO_COL)
        )
    except Exception as e:
        logger.error(f"Pipeline crashed: {str(e)}")
        logger.info("Restarting trigger in 5 seconds...")
        await asyncio.sleep(5)
        await run_trigger()
 
 
if __name__ == "__main__":
    try:
        asyncio.run(run_trigger())
    except KeyboardInterrupt:
        logger.info("Trigger stopped by user.")
    finally:
        close_db()
        
