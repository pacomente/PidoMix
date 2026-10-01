import { useCallback, useEffect, useRef, useState } from 'react';

/** Carga datos de la API con estados de carga/error y "tirar para actualizar". Se recarga cuando cambia algo de `deps`. */
export function useFetch<T>(loader: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const latest = useRef(0);
  const loaderRef = useRef(loader);
  useEffect(() => { loaderRef.current = loader; });
  const key = JSON.stringify(deps);

  const run = useCallback(async (isRefresh: boolean) => {
    const id = ++latest.current;
    if (isRefresh) setRefreshing(true);
    else setLoading(true);
    try {
      const result = await loaderRef.current();
      if (id === latest.current) { setData(result); setError(null); }
    } catch (e) {
      if (id === latest.current) setError(e instanceof Error ? e.message : 'Ocurrió un error.');
    } finally {
      if (id === latest.current) { setLoading(false); setRefreshing(false); }
    }
  }, []);

  // traer datos de la API es justo el caso de "sincronizar con un sistema externo"
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { run(false); }, [key, run]);
  return { data, error, loading, refreshing, reload: () => run(false), refresh: () => run(true), setData };
}
