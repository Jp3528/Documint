import { useEffect, useState } from "react";
import { z } from "zod";
import { apiRequest, errorMessage } from "./api";

export function useResource<T>(path: string, schema: z.ZodType<T>, revision = 0) {
  const key = `${path}#${revision}`;
  const [state, setState] = useState<{ key: string; data: T | null; error: string }>({
    key: "",
    data: null,
    error: "",
  });
  useEffect(() => {
    const controller = new AbortController();
    void apiRequest(path, { signal: controller.signal })
      .then((value) => {
        const data = schema.parse(value);
        if (!controller.signal.aborted) setState({ key, data, error: "" });
      })
      .catch((error) => {
        if (!controller.signal.aborted) setState({ key, data: null, error: errorMessage(error) });
      });
    return () => controller.abort();
  }, [path, schema, key]);
  return {
    data: state.key === key ? state.data : null,
    error: state.key === key ? state.error : "",
    loading: state.key !== key,
  };
}
