import type { TaskEvent } from "./console-types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

class ApiClient {
  accessToken = "";
  refreshToken = "";

  restore() {
    this.accessToken = localStorage.getItem("eap_access_token") || "";
    this.refreshToken =
      localStorage.getItem("eap_refresh_token") || "";
  }

  save(accessToken: string, refreshToken: string) {
    this.accessToken = accessToken;
    this.refreshToken = refreshToken;
    localStorage.setItem("eap_access_token", accessToken);
    localStorage.setItem("eap_refresh_token", refreshToken);
  }

  clear() {
    this.accessToken = "";
    this.refreshToken = "";
    localStorage.removeItem("eap_access_token");
    localStorage.removeItem("eap_refresh_token");
  }

  async request<T>(
    path: string,
    options: RequestInit = {},
  ): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(this.accessToken
          ? { Authorization: `Bearer ${this.accessToken}` }
          : {}),
        ...options.headers,
      },
    });
    if (!response.ok) {
      let detail = `请求失败 (${response.status})`;
      try {
        const payload = await response.json();
        detail = payload.detail || detail;
      } catch {
        // Keep the status-based fallback message.
      }
      throw new Error(detail);
    }
    if (response.status === 204) return undefined as T;
    return response.json();
  }

  async streamTaskEvents(
    taskId: string,
    after: number,
    onEvent: (event: TaskEvent) => void,
    signal: AbortSignal,
  ): Promise<number> {
    const response = await fetch(
      `${API_BASE}/v1/tasks/${encodeURIComponent(taskId)}/events/stream?after=${after}`,
      {
        headers: this.accessToken
          ? { Authorization: `Bearer ${this.accessToken}` }
          : {},
        signal,
      },
    );
    if (!response.ok || !response.body) {
      throw new Error(`任务事件流连接失败 (${response.status})`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let cursor = after;
    while (!signal.aborted) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() || "";
      for (const frame of frames) {
        const data = frame
          .split(/\r?\n/)
          .find((line) => line.startsWith("data: "));
        if (!data) continue;
        const event = JSON.parse(data.slice(6)) as TaskEvent;
        cursor = Math.max(cursor, event.id || cursor);
        onEvent(event);
      }
      if (done) break;
    }
    return cursor;
  }

  async upload<T>(path: string, body: FormData): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: this.accessToken
        ? { Authorization: `Bearer ${this.accessToken}` }
        : {},
      body,
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || `文件上传失败 (${response.status})`);
    }
    return response.json();
  }
}

export const api = new ApiClient();
