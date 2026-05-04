import { useState, useEffect, useCallback, useRef } from "react";
import { API_URL } from "../config";

const PAGE_SIZE = 50;
const DEBOUNCE_MS = 500;

export const BASE_URL = `${API_URL}/invalid-summary`;

// Compute display total from a summary object + active filters
// No filters → sum all pipeline categories
// Filters → sum only the relevant keys
const VALIDATION_FILTER_KEY = "validation inprogress,validation initiated";
const STD_FILTER_KEY = "standardization inprogress";

function computeTotalFromSummary(summary, filters) {
  const get = (key) => summary[key] || 0;

  const getForFilter = (f) => {
    if (f === VALIDATION_FILTER_KEY) return get("VALIDATION_INITIATED") + get("VALIDATION_IN_PROGRESS");
    if (f === STD_FILTER_KEY)        return get("STANDARDIZATION_IN_PROGRESS");
    if (f === "pending")             return get("PENDING");
    if (f === "accepted")            return get("ACCEPTED");
    if (f === "rejected")            return get("REJECTED"); // L0 data = rejected
    if (f === "On Hold")             return get("ON HOLD");
    if (f === "<3")                  return get("green");
    if (f === "3-6")                 return get("yellow");
    if (f === ">6")                  return get("red");
    return 0;
  };

  if (!filters || filters.length === 0) {
    return (
      get("PENDING") +
      get("REJECTED") +
      get("ACCEPTED") +
      get("ON HOLD") +
      get("VALIDATION_INITIATED") +
      get("VALIDATION_IN_PROGRESS") +
      get("STANDARDIZATION_IN_PROGRESS")
    );
  }

  return filters.reduce((acc, f) => acc + getForFilter(f), 0);
}

export function usePaginatedRecords({ extraParams = {}, activeFilters = [] } = {}) {
  const [page, setPage] = useState(1);
  const [records, setRecords] = useState([]);
  const [totalRecords, setTotalRecords] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [meta, setMeta] = useState({});

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");

  const [isReadyState, setIsReadyState] = useState(false);

  const abortRef = useRef(null);
  const fetchIdRef = useRef(0);
  const activeFiltersRef = useRef(activeFilters);

  useEffect(() => {
    activeFiltersRef.current = activeFilters;
  }, [activeFilters]);

  const extraParamsKey = JSON.stringify(extraParams);

  useEffect(() => {
    return () => { if (abortRef.current) abortRef.current.abort(); };
  }, []);

  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput), DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [searchInput]);

  const fetchRecords = useCallback(
    async (pageNum, isNew = false) => {
      if (abortRef.current) abortRef.current.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      const fetchId = ++fetchIdRef.current;

      if (isNew) {
        setRecords([]);
        setTotalRecords(0);
        setTotalPages(0);
        setMeta({});
      }

      setLoading(true);
      setError(null);

      try {
        const parsed = JSON.parse(extraParamsKey);
        const baseParams = { page: pageNum, size: PAGE_SIZE, search: search || "", ...parsed };
        const qs = new URLSearchParams();
        Object.entries(baseParams).forEach(([k, v]) => qs.set(k, v));

        const res = await fetch(`${BASE_URL}?${qs}`, { signal: controller.signal });
        if (!res.ok) throw new Error(`Failed to fetch data: ${res.status}`);
        const data = await res.json();

        if (fetchId !== fetchIdRef.current) return;

        const incoming = (Array.isArray(data?.data) ? data.data : []).map((r) => ({
          ...r,
          ExecutionId: String(r.ExecutionId || r.execution_id || r.executionId || ""),
        }));

        // Always use total_records from the API as the source of truth
        const total = data?.total_invalid_records ?? incoming.length;

        setTotalPages(Math.ceil(total / PAGE_SIZE));
        setTotalRecords(total);
        setRecords((prev) => (isNew ? incoming : [...prev, ...incoming]));

        const { data: _d, total_invalid_records: _t, summary, ...rest } = data;
        setMeta({ ...rest, ...(summary || {}) });

        setIsReadyState(true);
      } catch (err) {
        if (fetchId !== fetchIdRef.current) return;
        if (err.name !== "AbortError") {
          console.error("usePaginatedRecords:", err);
          setError(err);
        }
      } finally {
        if (fetchId === fetchIdRef.current) setLoading(false);
      }
    },
    [search, extraParamsKey]
  );

  const patchRecords = useCallback((updates) => {
    const normalizedUpdates = updates.map((u) => ({
      ...u,
      ExecutionId: String(u.ExecutionId || u.execution_id || u.executionId || ""),
    }));
    const updateMap = new Map(normalizedUpdates.map((u) => [u.ExecutionId, u]));
    setRecords((prev) =>
      prev.map((r) => {
        const id = String(r.ExecutionId || r.execution_id || r.executionId || "");
        const up = updateMap.get(id);
        return up ? { ...r, ...up } : r;
      })
    );
  }, []);

  const removeRecords = useCallback((executionIds) => {
    const idSet = new Set(executionIds.map(String));
    setRecords((prev) => prev.filter((r) => !idSet.has(String(r.ExecutionId))));
    setTotalRecords((prev) => Math.max(0, prev - executionIds.length));
  }, []);

  // updateCounts: called on every WS summary message.
  // Updates meta, then recomputes totalRecords from the summary
  // using the currently active filters.
  const updateCounts = useCallback((summary) => {
    if (!summary) return;
    setMeta((prev) => ({ ...prev, ...summary }));

    const newTotal = computeTotalFromSummary(summary, activeFiltersRef.current);
    setTotalRecords(newTotal);
  }, []);

  useEffect(() => {
    setPage(1);
    fetchRecords(1, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, extraParamsKey]);

  useEffect(() => {
    if (page > 1) fetchRecords(page, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  const loadMore = useCallback(() => setPage((p) => p + 1), []);
  const retry = useCallback(() => fetchRecords(page, page === 1), [fetchRecords, page]);
  const refresh = useCallback(() => { setPage(1); fetchRecords(1, true); }, [fetchRecords]);

  return {
    records, totalRecords, totalPages, page, loading, error,
    searchInput, setSearchInput, search,
    loadMore, retry, refresh, meta,
    patchRecords, removeRecords, updateCounts, isReadyState,
  };
}