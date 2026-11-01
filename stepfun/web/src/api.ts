export interface Hit {
  id: string;
  text: string;
  metadata: Record<string, unknown>;
  distance: number | null;
}

export interface HealthInfo {
  ok: boolean;
  backend: string;
  name: string;
  dimension: number;
  distance: string;
  count: number;
}

export interface IndexRecord {
  id: string;
  text: string;
  embedding: number[];
  metadata: Record<string, string | number | boolean>;
}

const request = async <T>(path: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(path, {
    ...init,
    headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
  });
  const payload = (await response.json()) as unknown;
  if (!response.ok) {
    const message = (payload as { error?: string }).error ?? response.statusText;
    throw new Error(message);
  }
  return payload as T;
};

export const health = () => request<HealthInfo>('/api/health');

export const indexDocuments = (records: IndexRecord[]) =>
  request<{ inserted: number; dimension: number }>('/api/documents', {
    method: 'POST',
    body: JSON.stringify({ records }),
  });

export const search = (text: string, embedding: number[], topK: number) =>
  request<{ hits: Hit[]; elapsedMs: number; statement: string }>('/api/search', {
    method: 'POST',
    body: JSON.stringify({ text, embedding, topK }),
  });

export const resetLibrary = () =>
  request<{ ok: boolean; name: string; dimension: number; count: number }>('/api/reset', {
    method: 'POST',
    body: JSON.stringify({}),
  });