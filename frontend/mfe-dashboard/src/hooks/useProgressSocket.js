import { useEffect, useRef } from "react";
import { API_URL } from "../config";

const WS_URL = `${API_URL.replace(/^http/, "ws")}/ws`;

// Normalize stage string: "standardization completed" / "standardization_completed" → "standardization_completed"
const normalizeStage = (s) => s?.toLowerCase().trim().replace(/[\s_]+/g, "_") ?? "";

// Determine whether a WS stage update should trigger record removal.
//
// activeFilters = []           → Dashboard, no filters: never remove (just patch)
// activeFilters = [...]        → Dashboard with filters: filter-aware removal
//
// Dashboard removal rules (when stage filters are active):
//   • "validation inprogress" active, "standardization inprogress" NOT active
//     → remove when normalizedStage === "validation_completed"
//   • Any stage filter active AND "pending" NOT active
//     → remove when normalizedStage === "standardization_completed"
//   • "pending" active together with stage filters
//     → do NOT remove on standardization_completed
function shouldRemove(normalizedStage, activeFilters) {
  // Terminal failure stages: always remove from dashboard pipeline view
  if (normalizedStage === "validation_failed" || normalizedStage === "standardization_failed") {
    return true;
  }

  // Dashboard, no filters → never remove normal completions
  if (activeFilters.length === 0) return false;

  const hasValidation = activeFilters.includes("validation inprogress,validation initiated");
  const hasStd = activeFilters.includes("standardization inprogress");
  const hasPending = activeFilters.includes("pending");
  const hasAnyStage = hasValidation || hasStd;

  // No stage filters selected (only status filters like accepted/rejected/on hold)
  // → just patch, never remove
  if (!hasAnyStage) return false;

  // Validation filter only (std not selected) → remove when validation completes
  if (hasValidation && !hasStd && normalizedStage === "validation_completed") return true;

  // Any stage filter without pending → remove when std completes
  if (hasAnyStage && !hasPending && normalizedStage === "standardization_completed") return true;

  return false;
}

// Delay in ms between patching the final stage and removing the card
const REMOVAL_FLASH_DELAY_MS = 500;

export function useProgressSocket({
  patchRecords,
  removeRecords,
  updateCounts,   // called with WS summary object to update filter counts
  activeFilters,  // [] or [...] = dashboard
  isReady,
}) {
  // Keep activeFilters in a ref so the WS message handler always sees the latest
  // value without requiring the WebSocket to be re-created on every filter change.
  const activeFiltersRef = useRef(activeFilters);
  useEffect(() => {
    activeFiltersRef.current = activeFilters;
  }, [activeFilters]);

  useEffect(() => {
    if (!isReady) return;

    let ws = null;
    let reconnectTimer = null;
    let retryCount = 0;
    let disposed = false;
    const MAX_RETRY_DELAY = 30_000;

    // Track pending removal timers so we can cancel them on cleanup
    const pendingRemovals = new Map(); // String(ExecutionId) → timerId

    function connect() {
      if (disposed) return;

      console.log("[WS] Attempting connection to", WS_URL);
      ws = new WebSocket(WS_URL);

      ws.onopen = () => {
        console.log("[WS] ✅ Connected");
        retryCount = 0;
      };

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          console.log(message)
          if (message.type !== "PIPELINE_UPDATE") return;

          // ── Count / summary update ────────────────────────────────────────
          if (message.summary) {
            updateCounts?.(message.summary);
            // Message may ONLY contain a summary (no execution_id), so guard below
          }

          if (!message.execution_id && !message.ExecutionId) return;

          const ns = normalizeStage(message.stage);

          const record = {
            ExecutionId: String(message.execution_id || message.ExecutionId),
            Stage: message.stage,
            Status: message.status || message.Status,
            InvalidFields: message.invalidFields || message.invalid_fields || [],
            suggestionsCount: message.suggestionsCount || message.suggestions_count || false,
            updatedOn: message.updatedOn || message.updated_on,
            BenchmarkType: message.benchmarkType || message.benchmark_type,
            BenchmarkCategory: message.benchmarkCategory || message.benchmark_category,
          };

          const idKey = String(record.ExecutionId);
          console.log(`[WS] Processing update for ID: ${idKey}, New Stage: "${message.stage}" (Normalized: "${ns}")`);

          if (shouldRemove(ns, activeFiltersRef.current)) {
            // Cancel any existing pending removal for this record (e.g. double-fire)
            if (pendingRemovals.has(idKey)) {
              clearTimeout(pendingRemovals.get(idKey));
            }

            // 1. Patch with the stage so RecordCard shows the state (green flash or red failure).
            let displayStage = ns;
            if (ns === "validation_completed") displayStage = "validation_completing";
            if (ns === "standardization_completed") displayStage = "standardization_completing";

            patchRecords([{ ...record, Stage: displayStage }]);

            // 2. Remove the card after the flash delay
            const timer = setTimeout(() => {
              removeRecords?.([record.ExecutionId]);
              pendingRemovals.delete(idKey);
            }, REMOVAL_FLASH_DELAY_MS);

            pendingRemovals.set(idKey, timer);
          } else {
            // Non-removal case: if standardization completes, show a quick 100% bar flash 
            // before switching to the default "Status + Inconsistent Fields" UI.
            if (ns === "standardization_completed") {
              patchRecords([{ ...record, Stage: "standardization_completing" }]);
              setTimeout(() => {
                patchRecords([record]);
              }, REMOVAL_FLASH_DELAY_MS);
            } else {
              // Normal patch for all other intermediate stages
              patchRecords([record]);
            }
          }
        } catch (err) {
          console.error("[WS] ❌ Failed to parse message:", err, "Raw:", event.data);
        }
      };

      ws.onerror = (err) => console.error("[WS] ❌ Error:", err);

      ws.onclose = (event) => {
        if (disposed) {
          console.log("[WS] Closed (cleanup)");
          return;
        }
        const delay = Math.min(1000 * 2 ** retryCount, MAX_RETRY_DELAY);
        retryCount++;
        console.log(`[WS] ⚠️ Disconnected (code ${event.code}). Reconnecting in ${delay / 1000}s…`);
        reconnectTimer = setTimeout(connect, delay);
      };
    }

    connect();

    return () => {
      disposed = true;
      clearTimeout(reconnectTimer);
      // Cancel all pending removal timers so they don't fire after unmount
      pendingRemovals.forEach((timer) => clearTimeout(timer));
      pendingRemovals.clear();
      if (ws) ws.close();
    };
  }, [isReady, patchRecords, removeRecords, updateCounts]);
}