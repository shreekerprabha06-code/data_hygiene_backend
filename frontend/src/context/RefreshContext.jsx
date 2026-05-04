import { createContext, useContext, useRef, useCallback } from "react";

const RefreshContext = createContext(null);

export const RefreshProvider = ({ children }) => {
  const refreshRef = useRef(null);

  const registerRefresh = useCallback((fn) => {
    refreshRef.current = fn;
  }, []);

  const triggerRefresh = useCallback(() => {
    refreshRef.current?.();
  }, []);

  return (
    <RefreshContext.Provider value={{ registerRefresh, triggerRefresh }}>
      {children}
    </RefreshContext.Provider>
  );
};

export const useRefresh = () => useContext(RefreshContext);